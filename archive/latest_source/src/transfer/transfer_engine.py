class TransferEngine:

    def __init__(self):
        self.progress = 0
        self.status = "Idle"

    def start(self):
        self.status = "Transferring"
        return self.status