"""
PTZ Control - Pan/Tilt/Zoom camera control for Reolink E1 Pro
"""

import logging
import httpx
from typing import Optional, Dict, Any
from dataclasses import dataclass
import asyncio

logger = logging.getLogger(__name__)


@dataclass
class PTZPosition:
    pan: float
    tilt: float
    zoom: float


class ReolinkPTZController:
    """
    Controls Reolink E1 Pro PTZ camera via HTTP API.
    
    API endpoints:
    - http://CAMERA_IP/api.cgi?cmd=PtzCtrl&...
    """
    
    def __init__(
        self,
        camera_id: str,
        api_url: str,
        username: str = "admin",
        password: str = ""
    ):
        self.camera_id = camera_id
        self.api_url = api_url.rstrip("/")
        self.username = username
        self.password = password
        self._token: Optional[str] = None
        
        logger.info(f"PTZController initialized for camera {camera_id}")
    
    async def _get_token(self) -> Optional[str]:
        """Get authentication token from camera"""
        if self._token:
            return self._token
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.api_url}/api.cgi?cmd=Login",
                    json=[{
                        "cmd": "Login",
                        "param": {
                            "User": {
                                "Version": "0",
                                "userName": self.username,
                                "password": self.password
                            }
                        }
                    }]
                )
                
                data = response.json()
                if data and len(data) > 0:
                    self._token = data[0].get("value", {}).get("Token", {}).get("name")
                    return self._token
                    
        except Exception as e:
            logger.error(f"Failed to get PTZ token: {e}")
        
        return None
    
    async def _send_command(self, cmd: str, params: Dict[str, Any]) -> bool:
        """Send PTZ command to camera"""
        token = await self._get_token()
        
        try:
            url = f"{self.api_url}/api.cgi?cmd={cmd}"
            if token:
                url += f"&token={token}"
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json=[{
                        "cmd": cmd,
                        "param": params
                    }]
                )
                
                data = response.json()
                
                if data and len(data) > 0:
                    code = data[0].get("code", -1)
                    if code == 0:
                        return True
                    else:
                        logger.warning(f"PTZ command failed: {data}")
                        # Token might be expired
                        if code == 2:
                            self._token = None
                
        except Exception as e:
            logger.error(f"PTZ command error: {e}")
        
        return False
    
    async def pan_left(self, speed: int = 25) -> bool:
        """Pan camera left"""
        return await self._send_command("PtzCtrl", {
            "channel": 0,
            "op": "Left",
            "speed": min(max(speed, 1), 64)
        })
    
    async def pan_right(self, speed: int = 25) -> bool:
        """Pan camera right"""
        return await self._send_command("PtzCtrl", {
            "channel": 0,
            "op": "Right",
            "speed": min(max(speed, 1), 64)
        })
    
    async def tilt_up(self, speed: int = 25) -> bool:
        """Tilt camera up"""
        return await self._send_command("PtzCtrl", {
            "channel": 0,
            "op": "Up",
            "speed": min(max(speed, 1), 64)
        })
    
    async def tilt_down(self, speed: int = 25) -> bool:
        """Tilt camera down"""
        return await self._send_command("PtzCtrl", {
            "channel": 0,
            "op": "Down",
            "speed": min(max(speed, 1), 64)
        })
    
    async def zoom_in(self) -> bool:
        """Zoom camera in"""
        return await self._send_command("PtzCtrl", {
            "channel": 0,
            "op": "ZoomInc",
            "speed": 25
        })
    
    async def zoom_out(self) -> bool:
        """Zoom camera out"""
        return await self._send_command("PtzCtrl", {
            "channel": 0,
            "op": "ZoomDec",
            "speed": 25
        })
    
    async def stop(self) -> bool:
        """Stop PTZ movement"""
        return await self._send_command("PtzCtrl", {
            "channel": 0,
            "op": "Stop"
        })
    
    async def go_to_preset(self, preset_id: int) -> bool:
        """Move to preset position"""
        return await self._send_command("PtzCtrl", {
            "channel": 0,
            "op": "ToPos",
            "id": preset_id,
            "speed": 32
        })
    
    async def set_preset(self, preset_id: int, name: str = "") -> bool:
        """Save current position as preset"""
        return await self._send_command("PtzCtrl", {
            "channel": 0,
            "op": "SetPreset",
            "id": preset_id,
            "name": name or f"Preset {preset_id}"
        })
    
    async def get_position(self) -> Optional[PTZPosition]:
        """Get current PTZ position"""
        token = await self._get_token()
        
        try:
            url = f"{self.api_url}/api.cgi?cmd=GetPtzCurPos"
            if token:
                url += f"&token={token}"
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json=[{
                        "cmd": "GetPtzCurPos",
                        "param": {"channel": 0}
                    }]
                )
                
                data = response.json()
                
                if data and len(data) > 0:
                    value = data[0].get("value", {}).get("PtzCurPos", {})
                    return PTZPosition(
                        pan=value.get("Ppos", 0),
                        tilt=value.get("Tpos", 0),
                        zoom=value.get("Zpos", 0)
                    )
                    
        except Exception as e:
            logger.error(f"Failed to get PTZ position: {e}")
        
        return None
    
    async def move(self, direction: str, speed: int = 25) -> bool:
        """
        Move camera in direction.
        direction: left, right, up, down, zoom_in, zoom_out
        """
        direction = direction.lower()
        
        if direction == "left":
            return await self.pan_left(speed)
        elif direction == "right":
            return await self.pan_right(speed)
        elif direction == "up":
            return await self.tilt_up(speed)
        elif direction == "down":
            return await self.tilt_down(speed)
        elif direction == "zoom_in":
            return await self.zoom_in()
        elif direction == "zoom_out":
            return await self.zoom_out()
        elif direction == "stop":
            return await self.stop()
        else:
            logger.warning(f"Unknown PTZ direction: {direction}")
            return False


class PTZControllerManager:
    """
    Manages PTZ controllers for multiple cameras.
    """
    
    _instance: Optional['PTZControllerManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._controllers: Dict[str, ReolinkPTZController] = {}
        self._initialized = True
        logger.info("PTZControllerManager initialized")
    
    def add_controller(
        self,
        camera_id: str,
        api_url: str,
        username: str = "admin",
        password: str = ""
    ) -> ReolinkPTZController:
        """Add PTZ controller for camera"""
        controller = ReolinkPTZController(
            camera_id=camera_id,
            api_url=api_url,
            username=username,
            password=password
        )
        self._controllers[camera_id] = controller
        return controller
    
    def get_controller(self, camera_id: str) -> Optional[ReolinkPTZController]:
        """Get PTZ controller by camera ID"""
        return self._controllers.get(camera_id)
    
    def has_ptz(self, camera_id: str) -> bool:
        """Check if camera has PTZ support"""
        return camera_id in self._controllers
    
    async def move(
        self,
        camera_id: str,
        direction: str,
        speed: int = 25
    ) -> bool:
        """Move camera PTZ"""
        controller = self.get_controller(camera_id)
        if controller:
            return await controller.move(direction, speed)
        logger.warning(f"No PTZ controller for camera {camera_id}")
        return False
    
    async def go_to_preset(self, camera_id: str, preset_id: int) -> bool:
        """Move camera to preset"""
        controller = self.get_controller(camera_id)
        if controller:
            return await controller.go_to_preset(preset_id)
        return False
    
    async def stop(self, camera_id: str) -> bool:
        """Stop camera PTZ movement"""
        controller = self.get_controller(camera_id)
        if controller:
            return await controller.stop()
        return False


# Global PTZ manager instance
ptz_manager = PTZControllerManager()

