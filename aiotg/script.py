import asyncio

class ScriptManager:
    def __init__(self):
        self.chats = {}
    

    async def handle(self, user, msg):
        chat = self.chats.get(str(user), Chat(user))
        self.chats[str(user)] = chat
        if msg == 'subdomain':
            coro = self.play(chat, subdomain_script, msg)
            asyncio.ensure_future(coro)
        else:
            coro = chat.handle(msg)
            asyncio.ensure_future(coro)
          
