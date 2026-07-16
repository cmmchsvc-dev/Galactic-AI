from skills.base import GalacticSkill
import requests
import asyncio
import json

class SmartHomeSkill(GalacticSkill):
    skill_name = "smart_home"
    display_name = "Smart Home Control"
    version = "1.0.0"
    author = "cmmchsvc"
    description = "Controls local smart home devices (Philips Hue)."
    category = "automation"
    icon = "💡"

    def __init__(self, core):
        super().__init__(core)
        self.hue_config = self.core.config.get('smart_home', {}).get('hue', {})
        self.bridge_ip = self.hue_config.get('bridge_ip', '')
        self.api_username = self.hue_config.get('api_username', '')

    def get_tools(self):
        return {
            "list_lights": {
                "description": "Returns a list of all Philips Hue lights on the network, their IDs, and current power state.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                "fn": self._tool_list_lights
            },
            "set_light_state": {
                "description": "Turns a specific Philips Hue light on or off by its ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "light_id": {
                            "type": "string",
                            "description": "The ID of the light to control (e.g., '1', '2')."
                        },
                        "turn_on": {
                            "type": "boolean",
                            "description": "True to turn the light on, False to turn it off."
                        }
                    },
                    "required": ["light_id", "turn_on"]
                },
                "fn": self._tool_set_light_state
            },
            "register_hue_bridge": {
                "description": "Discovers the Hue Bridge on the network and attempts to register a new user. The user MUST press the physical link button on the bridge before running this.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                },
                "fn": self._tool_register_hue_bridge
            }
        }

    async def _tool_list_lights(self, args):
        if not self.bridge_ip or not self.api_username:
            return "[ERROR] Hue Bridge IP or Username not configured. Run 'register_hue_bridge' tool first after pressing the link button on your bridge."
            
        try:
            url = f"http://{self.bridge_ip}/api/{self.api_username}/lights"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            lights = response.json()
            
            output = []
            for l_id, info in lights.items():
                state = "ON" if info['state']['on'] else "OFF"
                output.append(f"ID: {l_id} | Name: {info['name']} | State: {state}")
                
            return "\n".join(output) if output else "No lights found."
        except Exception as e:
            return f"[ERROR] Failed to list lights: {e}"

    async def _tool_set_light_state(self, args):
        if not self.bridge_ip or not self.api_username:
            return "[ERROR] Hue Bridge not configured."
            
        l_id = args.get("light_id")
        turn_on = args.get("turn_on")
        
        try:
            url = f"http://{self.bridge_ip}/api/{self.api_username}/lights/{l_id}/state"
            payload = {"on": turn_on}
            response = requests.put(url, json=payload, timeout=5)
            response.raise_for_status()
            
            return f"Light {l_id} successfully turned {'ON' if turn_on else 'OFF'}."
        except Exception as e:
            return f"[ERROR] Failed to set light state: {e}"

    async def _tool_register_hue_bridge(self, args):
        try:
            # 1. Discover Bridge IP via meethue API
            if not self.bridge_ip:
                discovery_resp = requests.get("https://discovery.meethue.com/", timeout=5)
                discovery_resp.raise_for_status()
                bridges = discovery_resp.json()
                if not bridges:
                    return "[ERROR] Could not discover any Hue Bridges on the local network."
                
                self.bridge_ip = bridges[0]['internalipaddress']
                
            # 2. Register user
            url = f"http://{self.bridge_ip}/api"
            payload = {"devicetype": "galactic_ai#desktop"}
            reg_resp = requests.post(url, json=payload, timeout=5)
            reg_resp.raise_for_status()
            result = reg_resp.json()[0]
            
            if 'error' in result:
                if result['error']['type'] == 101:
                    return f"[WARNING] Found bridge at {self.bridge_ip}, but link button not pressed. Please go press the physical button on your Hue Bridge and run this tool again."
                return f"[ERROR] Registration failed: {result['error']}"
                
            if 'success' in result:
                self.api_username = result['success']['username']
                
                # Save to config
                import yaml, os
                cfg_path = os.path.join(self.core.config['paths']['workspace'], 'config.yaml')
                with open(cfg_path, 'r') as f:
                    yml = yaml.safe_load(f)
                    
                if 'smart_home' not in yml:
                    yml['smart_home'] = {}
                if 'hue' not in yml['smart_home']:
                    yml['smart_home']['hue'] = {}
                    
                yml['smart_home']['hue']['bridge_ip'] = self.bridge_ip
                yml['smart_home']['hue']['api_username'] = self.api_username
                
                with open(cfg_path, 'w') as f:
                    yaml.dump(yml, f, sort_keys=False)
                    
                self.core.config = yml
                return f"✅ Successfully registered with Hue Bridge! IP: {self.bridge_ip} | Username saved to config.yaml. You can now control lights."
                
        except Exception as e:
            return f"[ERROR] Registration process failed: {e}"
