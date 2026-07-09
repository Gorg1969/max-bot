class UserState:
    """Состояния пользователей"""
    
    def __init__(self):
        self.publications = {}
    
    def start_publication(self, user_id):
        self.publications[user_id] = True
    
    def stop_publication(self, user_id):
        self.publications[user_id] = False
    
    def is_publication_active(self, user_id):
        return self.publications.get(user_id, False)
