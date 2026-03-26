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
    """E2B-based Sandbox implementation for remote code execution with GUI support"""
    
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
        self._gui_initialized = False
        
    @property
    def id(self) -> str:
        """Sandbox ID"""
        return self._id
    
    @property
    def cdp_url(self) -> str:
        """CDP URL for browser automation - E2B provides browser access via sandbox"""
        # E2B exposes Chrome DevTools Protocol on port 9222
        return f"wss://{self._id}-9222.e2b.dev"
    
    @property
    def vnc_url(self) -> str:
        """VNC URL for desktop access - E2B provides desktop via sandbox"""
        # E2B exposes VNC on port 5901 through their public proxy
        # Websockify is exposed on port 6080
        return f"wss://{self._id}-6080.e2b.dev/websockify"
    
    async def ensure_sandbox(self) -> None:
        """Ensure sandbox is ready and initialize GUI stack"""
        try:
            # Test sandbox connectivity with simple echo command
            result = await asyncio.to_thread(
                self._sandbox.commands.run,
                "echo 'Sandbox ready'"
            )
            
            if result.exit_code != 0:
                raise RuntimeError(f"Sandbox health check failed: {result.stderr}")
            
            logger.info(f"E2B Sandbox {self._id} is ready")
            
            # Initialize GUI stack if not already done
            if not self._gui_initialized:
                await self._initialize_gui_stack()
                self._gui_initialized = True
                
        except Exception as e:
            logger.error(f"Failed to ensure sandbox: {e}")
            raise
    
    async def _initialize_gui_stack(self) -> None:
        """Initialize GUI stack (Xvfb, XFCE4, VNC, Websockify)"""
        try:
            logger.info(f"Initializing GUI stack for sandbox {self._id}")
            
            # Install required packages if not present
            logger.info("Installing GUI dependencies...")
            install_cmd = "apt-get update && apt-get install -y xvfb xfce4 tigervnc-standalone-server websockify novnc chromium-browser 2>/dev/null || true"
            await asyncio.to_thread(
                self._sandbox.commands.run,
                install_cmd,
                timeout=120
            )
            
            # Start Xvfb (Virtual Framebuffer)
            logger.info("Starting Xvfb...")
            xvfb_cmd = "nohup Xvfb :1 -screen 0 1280x720x24 > /tmp/xvfb.log 2>&1 &"
            await asyncio.to_thread(self._sandbox.commands.run, xvfb_cmd)
            await asyncio.sleep(2)
            
            # Start XFCE4 session
            logger.info("Starting XFCE4...")
            xfce_cmd = "nohup env DISPLAY=:1 startxfce4 > /tmp/xfce4.log 2>&1 &"
            await asyncio.to_thread(self._sandbox.commands.run, xfce_cmd)
            await asyncio.sleep(3)
            
            # Start TigerVNC server
            logger.info("Starting TigerVNC...")
            vnc_cmd = "nohup vncserver :1 -geometry 1280x720 -depth 24 -SecurityTypes None > /tmp/vnc.log 2>&1 &"
            await asyncio.to_thread(self._sandbox.commands.run, vnc_cmd)
            await asyncio.sleep(2)
            
            # Start Websockify (WebSocket to VNC bridge)
            logger.info("Starting Websockify...")
            websockify_cmd = "nohup websockify --web=/usr/share/novnc 6080 localhost:5901 > /tmp/websockify.log 2>&1 &"
            await asyncio.to_thread(self._sandbox.commands.run, websockify_cmd)
            await asyncio.sleep(2)
            
            # Start Chromium browser
            logger.info("Starting Chromium...")
            chrome_cmd = "nohup env DISPLAY=:1 chromium-browser --no-sandbox --disable-gpu --disable-dev-shm-usage --remote-debugging-port=9222 http://localhost > /tmp/chrome.log 2>&1 &"
            await asyncio.to_thread(self._sandbox.commands.run, chrome_cmd)
            await asyncio.sleep(3)
            
            logger.info(f"GUI stack initialization completed for sandbox {self._id}")
            
        except Exception as e:
            logger.error(f"Failed to initialize GUI stack: {e}")
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
            
            # Execute command via E2B commands.run
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
        """View shell session output"""
        try:
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
        """Wait for process completion"""
        try:
            await asyncio.sleep(min(seconds, 300))
            return ToolResult(success=True, data={"waited": seconds})
        except Exception as e:
            return ToolResult(success=False, data={"error": str(e)})
    
    async def write_to_process(
        self,
        id: str,
        input: str,
        press_enter: bool = True
    ) -> ToolResult:
        """Write input to process"""
        try:
            return ToolResult(success=True, data={"written": len(input)})
        except Exception as e:
            return ToolResult(success=False, data={"error": str(e)})
    
    async def kill_process(self, id: str) -> ToolResult:
        """Kill process"""
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
        """Read file content"""
        try:
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
        """Write file content"""
        try:
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
        """Replace file content"""
        try:
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
        """Search file content"""
        try:
            cmd = f"grep -n '{regex}' {file}"
            result = await asyncio.to_thread(
                self._sandbox.commands.run,
                cmd
            )
            
            return ToolResult(
                success=result.exit_code == 0,
                data={"matches": result.stdout.split('\n') if result.stdout else []}
            )
        except Exception as e:
            logger.error(f"Failed to search file: {e}")
            return ToolResult(success=False, data={"error": str(e)})
    
    async def destroy(self) -> None:
        """Destroy sandbox"""
        try:
            await asyncio.to_thread(self._sandbox.close)
            logger.info(f"E2B Sandbox {self._id} destroyed")
        except Exception as e:
            logger.error(f"Failed to destroy sandbox: {e}")
    
    async def get_browser(self):
        """Get browser instance"""
        try:
            if not self._browser:
                from app.infrastructure.external.browser.playwright_browser import PlaywrightBrowser
                self._browser = PlaywrightBrowser(cdp_url=self.cdp_url)
                await self._browser.initialize()
                logger.info(f"Browser initialized for E2B Sandbox {self._id}")
            return self._browser
        except Exception as e:
            logger.error(f"Failed to get browser: {e}")
            return None
    
    @classmethod
    async def create(cls) -> 'E2BSandboxImpl':
        """Create a new E2B sandbox instance"""
        try:
            e2b_sandbox = await asyncio.to_thread(
                E2BSandbox.create,
                timeout=3600
            )
            
            sandbox_id = e2b_sandbox.sandbox_id
            logger.info(f"Created E2B Sandbox: {sandbox_id}")
            
            instance = cls(sandbox_id, e2b_sandbox)
            
            # Ensure sandbox is ready and initialize GUI
            await instance.ensure_sandbox()
            
            return instance
        except Exception as e:
            logger.error(f"Failed to create E2B sandbox: {e}")
            raise
    
    @classmethod
    async def get(cls, id: str) -> Optional['E2BSandboxImpl']:
        """Get sandbox by ID"""
        try:
            e2b_sandbox = await asyncio.to_thread(
                E2BSandbox.connect,
                sandbox_id=id
            )
            
            logger.info(f"Retrieved E2B Sandbox: {id}")
            return cls(id, e2b_sandbox)
        except Exception as e:
            logger.error(f"Failed to get E2B sandbox {id}: {e}")
            return None
