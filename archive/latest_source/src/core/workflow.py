class Workflow:

    def __init__(self):
        self.state = "Idle"

    def update(self, state):
        self.state = state
        return self.state