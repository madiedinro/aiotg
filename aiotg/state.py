




class StateProxy:
    def __init__(self, state, channel):
        self.state = state
        self.channel = channel

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if not exc_value:
            pass
        print(exc_value)


class StateManager:

    def __init__(self):
        self._state = {}

    def get(self, key):
        return self._state.get(key)

    def set(self, key, val):
        self._state[key] = val

    def wrap(self, channel):
        return StateProxy(self, channel)
