import json
import os
from typing import Dict, Any, Optional

class UserState:
    """Хранилище состояний пользователей"""
    
    def __init__(self, data_file='data/user_states.json'):
        self.data_file = data_file
        self.states: Dict[int, Dict[str, Any]] = {}
        self._load()
    
    def _load(self):
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    self.states = json.load(f)
        except:
            self.states = {}
    
    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.states, f, ensure_ascii=False, indent=2)
        except:
            pass
    
    def get_state(self, user_id: int) -> Optional[str]:
        if user_id in self.states:
            return self.states[user_id].get('state')
        return None
    
    def set_state(self, user_id: int, state: str, data: dict = None):
        if user_id not in self.states:
            self.states[user_id] = {}
        self.states[user_id]['state'] = state
        if data:
            self.states[user_id]['data'] = data
        self._save()
    
    def get_data(self, user_id: int) -> dict:
        if user_id in self.states:
            return self.states[user_id].get('data', {})
        return {}
    
    def clear_state(self, user_id: int):
        if user_id in self.states:
            del self.states[user_id]
            self._save()
