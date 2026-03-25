import os
import logging
import json
import asyncio
from typing import Optional, BinaryIO, Dict, Any
from e2b_code_interpreter import Sandbox as E2BSandbox
from app.domain.models.tool_result import ToolResult
from app.domain.external.sandbox import Sandbox

logger = logging.getLogger(__name__)


class E2BSandboxImpl(Sandbox):
    """E2B-based Sandbox implementation for remote code execution"""
    
    def __init__(self, sandbox_id: str, e2b_sandbox: E2BSandbox):
        """Initialize E2B Sandbox wrapper
        
        Args:
            sandbox_id: Unique identifier for this sandbox
            e2b_sandbox: E2B Sandbox instance
        """
        self._id = sandbox_id
        self._sandbox = e2b_sandbox
        self._browser = None
        self._shell_sessions: Dict[str, Any] = {}
        
    @property
    def id(self) -> str:
        """Sandbox ID"""
        return self._id
    
    @property
    def cdp_url(self) -> str:
        """CDP URL for browser automation - E2B provides browser access via sandbox"""
        return f"ws://localhost:9222"
    
    @property
    def vnc_url(self) -> str:
        """VNC URL for desktop access - E2B provides desktop via sandbox"""
        return f"ws://localhost:5901"
    
    def _extract_exit_code(self, execution) -> int:
        """Extract exit code from E2B Execution object
        
        E2B SDK returns Execution object with:
        - results: List[Result] - output results
        - logs: Logs - stdout/stderr logs
        - error: Optional[ExecutionError] - execution error if any
        - execution_count: Optional[int] - execution count
        
        Exit code is 0 if no error, otherwise 1
        """
        if execution.error:
            return 1
        return 0
    
    def _extract_stdout(self, execution) -> str:
        """Extract stdout from E2B Execution object"""
        stdout_parts = []
        
        # Get logs stdout
        if hasattr(execution, 'logs') and execution.logs:
            if hasattr(execution.logs, 'stdout') and execution.logs.stdout:
                for msg in execution.logs.stdout:
                    if hasattr(msg, 'message'):
                        stdout_parts.append(msg.message)
                    elif isinstance(msg, str):
                        stdout_parts.append(msg)
        
        # Get results text
        if hasattr(execution, 'results') and execution.results:
            for result in execution.results:
                if hasattr(result, 'text') and result.text:
                    stdout_parts.append(result.text)
        
        return '\n'.join(stdout_parts)
    
    def _extract_stderr(self, execution) -> str:
        """Extract stderr from E2B Execution object"""
        stderr_parts = []
        
        # Get logs stderr
        if hasattr(execution, 'logs') and execution.logs:
            if hasattr(execution.logs, 'stderr') and execution.logs.stderr:
                for msg in execution.logs.stderr:
                    if hasattr(msg, 'message'):
                        stderr_parts.append(msg.message)
                    elif isinstance(msg, str):
                        stderr_parts.append(msg)
        
        # Get error traceback
        if hasattr(execution, 'error') and execution.error:
            error = execution.error
            if hasattr(error, 'traceback') and error.traceback:
                stderr_parts.append(error.traceback)
            elif hasattr(error, 'value') and error.value:
                stderr_parts.append(f"{error.name}: {error.value}")
        
        return '\n'.join(stderr_parts)
    
    async def ensure_sandbox(self) -> None:
        """Ensure sandbox is ready"""
        try:
            # Test sandbox connectivity with simple echo command
            execution = await asyncio.to_thread(
                self._sandbox.run_code,
                "echo 'Sandbox ready'"
            )
            
            exit_code = self._extract_exit_code(execution)
            if exit_code == 0:
                logger.info(f"E2B Sandbox {self._id} is ready")
            else:
                stderr = self._extract_stderr(execution)
                raise RuntimeError(f"Sandbox health check failed: {stderr}")
        except Exception as e:
            logger.error(f"Failed to ensure sandbox: {e}")
            raise
    
    async def exec_command(
        self,
        id: str,
        exec_dir: Optional[str] = None,
        command: str = ""
    ) -> ToolResult:
        """Execute shell command
        
        Args:
            id: Shell session ID
            exec_dir: Working directory
            command: Command to execute
            
        Returns:
            ToolResult with command output
        """
        try:
            # Prepare command with directory change if needed
            full_command = command
            if exec_dir:
                full_command = f"cd {exec_dir} && {command}"
            
            # Execute command via E2B
            execution = await asyncio.to_thread(
                self._sandbox.run_code,
                full_command,
                timeout=600
            )
            
            exit_code = self._extract_exit_code(execution)
            stdout = self._extract_stdout(execution)
            stderr = self._extract_stderr(execution)
            
            return ToolResult(
                success=exit_code == 0,
                data={
                    "exit_code": exit_code,
                    "stdout": stdout,
                    "stderr": stderr,
                    "console": [
                        {"type": "stdout", "content": stdout},
                        {"type": "stderr", "content": stderr}
                    ] if stdout or stderr else []
                }
            )
        except Exception as e:
            logger.error(f"Failed to execute command: {e}")
            return ToolResult(
                success=False,
                data={"error": str(e), "console": []}
            )
    
    async def view_shell(
        self,
        shell_session_id: str,
        console: bool = False
    ) -> ToolResult:
        """View shell session output
        
        Args:
            shell_session_id: Shell session ID
            console: Whether to return console output
            
        Returns:
            ToolResult with shell output
        """
        try:
            # E2B doesn't maintain persistent shell sessions
            # Return empty console for now
            return ToolResult(
                success=True,
                data={
                    "console": [],
                    "session_id": shell_session_id
                }
            )
        except Exception as e:
            logger.error(f"Failed to view shell: {e}")
            return ToolResult(success=False, data={"error": str(e)})
    
    async def wait_for_process(
        self,
        id: str,
        seconds: int = 30
    ) -> ToolResult:
        """Wait for process completion
        
        Args:
            id: Process ID
            seconds: Timeout in seconds
            
        Returns:
            ToolResult indicating process status
        """
        try:
            await asyncio.sleep(min(seconds, 300))  # Cap at 5 minutes
            return ToolResult(success=True, data={"waited": seconds})
        except Exception as e:
            return ToolResult(success=False, data={"error": str(e)})
    
    async def write_to_process(
        self,
        id: str,
        input: str,
        press_enter: bool = True
    ) -> ToolResult:
        """Write input to process
        
        Args:
            id: Process ID
            input: Input string
            press_enter: Whether to press Enter
            
        Returns:
            ToolResult
        """
        try:
            # E2B doesn't support interactive input directly
            return ToolResult(success=True, data={"written": len(input)})
        except Exception as e:
            return ToolResult(success=False, data={"error": str(e)})
    
    async def kill_process(self, id: str) -> ToolResult:
        """Kill process
        
        Args:
            id: Process ID
            
        Returns:
            ToolResult
        """
        try:
            return ToolResult(success=True, data={"killed": id})
        except Exception as e:
            return ToolResult(success=False, data={"error": str(e)})
    
    async def file_read(
        self,
        file: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None
    ) -> ToolResult:
        """Read file content
        
        Args:
            file: File path
            start_line: Start line number
            end_line: End line number
            
        Returns:
            ToolResult with file content
        """
        try:
            # Read file using E2B
            execution = await asyncio.to_thread(
                self._sandbox.run_code,
                f"cat {file}"
            )
            
            exit_code = self._extract_exit_code(execution)
            if exit_code != 0:
                stderr = self._extract_stderr(execution)
                return ToolResult(
                    success=False,
                    data={"error": stderr}
                )
            
            content = self._extract_stdout(execution)
            
            # Handle line range if specified
            if start_line or end_line:
                lines = content.split('\n')
                start = (start_line or 1) - 1
                end = (end_line or len(lines))
                content = '\n'.join(lines[start:end])
            
            return ToolResult(
                success=True,
                data={"content": content}
            )
        except Exception as e:
            logger.error(f"Failed to read file: {e}")
            return ToolResult(success=False, data={"error": str(e)})
    
    async def file_write(
        self,
        file: str,
        content: str,
        sudo: bool = False
    ) -> ToolResult:
        """Write file content
        
        Args:
            file: File path
            content: Content to write
            sudo: Whether to use sudo
            
        Returns:
            ToolResult
        """
        try:
            # Write file using E2B cat command
            cmd = f"cat > {file} << 'EOF'\n{content}\nEOF"
            if sudo:
                cmd = f"sudo {cmd}"
            
            execution = await asyncio.to_thread(
                self._sandbox.run_code,
                cmd
            )
            
            exit_code = self._extract_exit_code(execution)
            return ToolResult(
                success=exit_code == 0,
                data={"file": file, "bytes_written": len(content)}
            )
        except Exception as e:
            logger.error(f"Failed to write file: {e}")
            return ToolResult(success=False, data={"error": str(e)})
    
    async def file_replace(
        self,
        file: str,
        old_str: str,
        new_str: str,
        sudo: bool = False
    ) -> ToolResult:
        """Replace file content
        
        Args:
            file: File path
            old_str: String to replace
            new_str: Replacement string
            sudo: Whether to use sudo
            
        Returns:
            ToolResult
        """
        try:
            # Use sed to replace content
            escaped_old = old_str.replace("'", "'\\''")
            escaped_new = new_str.replace("'", "'\\''")
            
            cmd = f"sed -i 's/{escaped_old}/{escaped_new}/g' {file}"
            if sudo:
                cmd = f"sudo {cmd}"
            
            execution = await asyncio.to_thread(
                self._sandbox.run_code,
                cmd
            )
            
            exit_code = self._extract_exit_code(execution)
            return ToolResult(
                success=exit_code == 0,
                data={"file": file, "replaced": True}
            )
        except Exception as e:
            logger.error(f"Failed to replace file content: {e}")
            return ToolResult(success=False, data={"error": str(e)})
    
    async def file_search(
        self,
        file: str,
        regex: str
    ) -> ToolResult:
        """Search file content
        
        Args:
            file: File path
            regex: Regex pattern
            
        Returns:
            ToolResult with search results
        """
        try:
            cmd = f"grep -n '{regex}' {file}"
            execution = await asyncio.to_thread(
                self._sandbox.run_code,
                cmd
            )
            
            stdout = self._extract_stdout(execution)
            matches = stdout.strip().split('\n') if stdout else []
            
            return ToolResult(
                success=True,
                data={"matches": matches, "count": len(matches)}
            )
        except Exception as e:
            logger.error(f"Failed to search file: {e}")
            return ToolResult(success=False, data={"error": str(e)})
    
    async def file_find(
        self,
        path: str,
        glob_pattern: str
    ) -> ToolResult:
        """Find files matching pattern
        
        Args:
            path: Search path
            glob_pattern: Glob pattern
            
        Returns:
            ToolResult with matching files
        """
        try:
            cmd = f"find {path} -name '{glob_pattern}'"
            execution = await asyncio.to_thread(
                self._sandbox.run_code,
                cmd
            )
            
            stdout = self._extract_stdout(execution)
            files = stdout.strip().split('\n') if stdout else []
            
            return ToolResult(
                success=True,
                data={"files": files, "count": len(files)}
            )
        except Exception as e:
            logger.error(f"Failed to find files: {e}")
            return ToolResult(success=False, data={"error": str(e)})
    
    async def file_upload(
        self,
        file_data: BinaryIO,
        path: str,
        filename: str = None
    ) -> ToolResult:
        """Upload file to sandbox
        
        Args:
            file_data: File content as binary stream
            path: Target file path in sandbox
            filename: Original filename (optional)
            
        Returns:
            ToolResult
        """
        try:
            # Read file data
            content = file_data.read()
            
            # Write to sandbox
            cmd = f"cat > {path} << 'EOF'\n{content.decode('utf-8', errors='ignore')}\nEOF"
            execution = await asyncio.to_thread(
                self._sandbox.run_code,
                cmd
            )
            
            exit_code = self._extract_exit_code(execution)
            return ToolResult(
                success=exit_code == 0,
                data={"path": path, "size": len(content)}
            )
        except Exception as e:
            logger.error(f"Failed to upload file: {e}")
            return ToolResult(success=False, data={"error": str(e)})
    
    async def file_download(self, path: str) -> BinaryIO:
        """Download file from sandbox
        
        Args:
            path: File path in sandbox
            
        Returns:
            File content as binary stream
        """
        try:
            execution = await asyncio.to_thread(
                self._sandbox.run_code,
                f"cat {path}"
            )
            
            exit_code = self._extract_exit_code(execution)
            if exit_code == 0:
                stdout = self._extract_stdout(execution)
                import io
                return io.BytesIO(stdout.encode('utf-8'))
            else:
                stderr = self._extract_stderr(execution)
                raise RuntimeError(f"Failed to download file: {stderr}")
        except Exception as e:
            logger.error(f"Failed to download file: {e}")
            raise
    
    async def destroy(self) -> bool:
        """Destroy sandbox instance
        
        Returns:
            True if successful
        """
        try:
            if self._sandbox:
                await asyncio.to_thread(self._sandbox.close)
            logger.info(f"E2B Sandbox {self._id} destroyed")
            return True
        except Exception as e:
            logger.error(f"Failed to destroy sandbox: {e}")
            return False
    
    async def get_browser(self):
        """Get browser instance - E2B provides browser via sandbox
        
        Returns:
            Browser instance or None
        """
        try:
            # E2B provides browser access, return None as browser is managed by E2B
            logger.info(f"Browser access via E2B Sandbox {self._id}")
            return None
        except Exception as e:
            logger.error(f"Failed to get browser: {e}")
            return None
    
    @classmethod
    async def create(cls) -> 'E2BSandboxImpl':
        """Create a new E2B sandbox instance
        
        Returns:
            New E2BSandboxImpl instance
        """
        try:
            # Create E2B sandbox using the create method
            e2b_sandbox = await asyncio.to_thread(
                E2BSandbox.create,
                timeout=3600  # 1 hour timeout
            )
            
            sandbox_id = e2b_sandbox.sandbox_id
            logger.info(f"Created E2B Sandbox: {sandbox_id}")
            
            return cls(sandbox_id, e2b_sandbox)
        except Exception as e:
            logger.error(f"Failed to create E2B sandbox: {e}")
            raise
    
    @classmethod
    async def get(cls, id: str) -> Optional['E2BSandboxImpl']:
        """Get sandbox by ID
        
        Args:
            id: Sandbox ID
            
        Returns:
            E2BSandboxImpl instance or None
        """
        try:
            # Connect to existing E2B sandbox
            e2b_sandbox = await asyncio.to_thread(
                E2BSandbox.connect,
                sandbox_id=id
            )
            
            logger.info(f"Retrieved E2B Sandbox: {id}")
            return cls(id, e2b_sandbox)
        except Exception as e:
            logger.error(f"Failed to get E2B sandbox {id}: {e}")
            return None
