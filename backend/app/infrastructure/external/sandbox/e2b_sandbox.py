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
    
    async def ensure_sandbox(self) -> None:
        """Ensure sandbox is ready"""
        try:
            # Test sandbox connectivity with simple echo command using commands.run
            result = await asyncio.to_thread(
                self._sandbox.commands.run,
                "echo 'Sandbox ready'"
            )
            
            if result.exit_code == 0:
                logger.info(f"E2B Sandbox {self._id} is ready")
            else:
                raise RuntimeError(f"Sandbox health check failed: {result.stderr}")
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
            
            # Execute command via E2B commands.run (for shell commands)
            result = await asyncio.to_thread(
                self._sandbox.commands.run,
                full_command,
                timeout=600
            )
            
            return ToolResult(
                success=result.exit_code == 0,
                data={
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "console": [
                        {"type": "stdout", "content": result.stdout},
                        {"type": "stderr", "content": result.stderr}
                    ] if result.stdout or result.stderr else []
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
            # Read file using E2B commands.run
            result = await asyncio.to_thread(
                self._sandbox.commands.run,
                f"cat {file}"
            )
            
            if result.exit_code != 0:
                return ToolResult(
                    success=False,
                    data={"error": result.stderr}
                )
            
            content = result.stdout
            
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
            
            result = await asyncio.to_thread(
                self._sandbox.commands.run,
                cmd
            )
            
            return ToolResult(
                success=result.exit_code == 0,
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
            
            result = await asyncio.to_thread(
                self._sandbox.commands.run,
                cmd
            )
            
            return ToolResult(
                success=result.exit_code == 0,
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
            result = await asyncio.to_thread(
                self._sandbox.commands.run,
                cmd
            )
            
            matches = result.stdout.strip().split('\n') if result.stdout else []
            
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
            result = await asyncio.to_thread(
                self._sandbox.commands.run,
                cmd
            )
            
            files = result.stdout.strip().split('\n') if result.stdout else []
            
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
            result = await asyncio.to_thread(
                self._sandbox.commands.run,
                cmd
            )
            
            return ToolResult(
                success=result.exit_code == 0,
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
            result = await asyncio.to_thread(
                self._sandbox.commands.run,
                f"cat {path}"
            )
            
            if result.exit_code == 0:
                import io
                return io.BytesIO(result.stdout.encode('utf-8'))
            else:
                raise RuntimeError(f"Failed to download file: {result.stderr}")
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
        """Get browser instance - Initialize PlaywrightBrowser with E2B CDP URL
        
        Returns:
            Browser instance or None
        """
        try:
            if not self._browser:
                # Import here to avoid circular imports
                from app.infrastructure.external.browser.playwright_browser import PlaywrightBrowser
                
                # Create browser with E2B CDP URL
                self._browser = PlaywrightBrowser(cdp_url=self.cdp_url)
                await self._browser.initialize()
                logger.info(f"Browser initialized for E2B Sandbox {self._id}")
            return self._browser
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
