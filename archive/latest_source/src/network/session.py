class NetworkSession:

    def __init__(self):
        self.connected = False

    def connect(self, device):
        self.connected = True
        return self.connected