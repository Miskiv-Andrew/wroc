# devices/commands.py

class Command:
    def __init__(self, name: str, data: bytes, length: int):
        self.name = name
        self.data = data
        self.length = length

    def __repr__(self):
        return f"<Command {self.name}, len = {self.length}>"

# Константы команд
COMMAND_RAD_DOSE              = Command("RAD_DOSE", bytes([0x55, 0xAA, 0x70, 0x01, 0x00]), 12)
COMMAND_SER_NUM               = Command("SER_NUM",  bytes([0x55, 0xAA, 0x70, 0x01, 0x05]), 11)
COMMAND_RAD_INTENS            = Command("RAD_INTENS", bytes([0x55, 0xAA, 0x70, 0x01, 0x04]), 10)
COMMAND_TEMP                  = Command("TEMP", bytes([0x55, 0xAA, 0x70, 0x01, 0x08]), 8)
COMMAND_START_SIMPLE_SPECTRE  = Command("START_SIMPLE_SPECTRE", bytes([0x55, 0xAA, 0x70, 0x01, 0x8B, 0x09, 0x8C, 0x01]), 2076)
COMMAND_GET_SIMPLE_SPECTRE    = Command("GET_SIMPLE_SPECTRE", bytes([0x55, 0xAA, 0x70, 0x01, 0x8B, 0x00, 0x00, 0x00]), 2076)
COMMAND_CHANGE_ADDRESS        = Command("CHANGE_ADDRESS", bytes([0x55, 0xAA, 0x70, 0x00, 0x06, 0x00, 0x00]), 6)
