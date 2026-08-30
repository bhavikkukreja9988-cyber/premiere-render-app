class ChunkManager:

    def split(self, data, size=4194304):
        return [
            data[i:i+size]
            for i in range(0, len(data), size)
        ]