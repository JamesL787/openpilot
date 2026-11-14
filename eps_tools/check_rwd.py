#!/usr/bin/env python3
# Usage: python3 check_rwd.py <file.rwd> [file2.rwd ...]

import struct
import sys

DECRYPT_LOOKUP = {144: 72, 218: 55, 255: 255, 164: 1, 195: 26, 99: 2, 28: 178, 205: 158, 125: 138, 45: 118, 222: 98, 142: 78, 62: 58, 243: 38, 163: 18, 83: 254, 3: 234, 172: 214, 92: 194, 12: 174, 189: 154, 109: 134, 29: 114, 206: 94, 126: 74, 46: 54, 227: 34, 147: 14, 113: 0, 67: 250, 236: 230, 156: 210, 76: 190, 252: 170, 173: 150, 93: 130, 13: 110, 148: 253, 120: 159, 199: 148, 198: 137, 77: 126, 23: 104, 73: 83, 203: 73, 78: 62, 123: 53, 254: 42, 43: 33, 90: 23, 161: 12, 10: 3, 132: 249, 191: 239, 226: 220, 197: 201, 248: 191, 117: 181, 34: 172, 37: 161, 88: 151, 141: 142, 8: 131, 134: 121, 185: 111, 54: 101, 190: 90, 57: 79, 128: 68, 139: 57, 14: 46, 138: 35, 131: 10, 100: 241, 1: 228, 146: 200, 133: 185, 168: 171, 104: 155, 40: 139, 251: 85, 94: 66, 91: 45, 103: 124, 55: 112, 231: 156, 80: 56, 224: 92, 102: 113, 96: 60, 98: 188, 97: 252, 140: 206, 122: 31, 232: 187, 16: 40, 202: 51, 26: 7, 239: 251, 5: 153, 219: 77, 119: 128, 21: 157, 238: 102, 180: 5, 217: 119, 30: 50, 7: 100, 32: 44, 183: 144, 50: 176, 110: 70, 157: 146, 2: 164, 44: 182, 145: 8, 58: 15, 27: 29, 64: 52, 9: 67, 31: 199, 179: 22, 42: 11, 193: 20, 211: 30, 129: 4, 241: 32, 74: 19, 178: 208, 247: 160, 112: 64, 242: 224, 114: 192, 165: 193, 0: 36, 59: 37, 196: 9, 154: 39, 75: 41, 72: 147, 249: 127, 162: 204, 130: 196, 229: 209, 182: 133, 48: 48, 86: 109, 240: 96, 137: 99, 151: 136, 209: 24, 108: 198, 181: 197, 212: 13, 244: 21, 11: 25, 118: 117, 228: 17, 214: 141, 52: 229, 160: 76, 115: 6, 106: 27, 56: 143, 25: 71, 36: 225, 194: 212, 208: 88, 187: 69, 171: 65, 153: 103, 38: 97, 207: 243, 82: 184, 184: 175, 188: 218, 213: 205, 121: 95, 15: 195, 81: 248, 24: 135, 70: 105, 150: 125, 174: 86, 158: 82, 220: 226, 201: 115, 71: 116, 51: 246, 177: 16, 176: 80, 22: 93, 39: 108, 159: 231, 223: 247, 186: 47, 169: 107, 245: 213, 235: 81, 192: 84, 124: 202, 175: 235, 84: 237, 79: 211, 234: 59, 143: 227, 237: 166, 33: 236, 253: 106, 65: 244, 111: 219, 200: 179, 101: 177, 17: 232, 20: 221, 166: 129, 60: 186, 61: 122, 167: 140, 204: 222, 87: 120, 41: 75, 135: 132, 136: 163, 49: 240, 250: 63, 107: 49, 170: 43, 18: 168, 221: 162, 35: 242, 225: 28, 149: 189, 85: 173, 152: 167, 95: 215, 53: 165, 89: 87, 66: 180, 6: 89, 47: 203, 210: 216, 215: 152, 233: 123, 116: 245, 127: 223, 19: 238, 69: 169, 105: 91, 4: 217, 216: 183, 68: 233, 63: 207, 155: 61, 246: 149, 230: 145}

# Every image gets the same checks, whatever the vehicle: the firmware block
# ends with a 16-bit word sum at length - 0x80 and a negative word sum at
# length - 2 (each over all preceding words of the decrypted block).
SUM_TRAILER = 0x80
NEGATIVE_SUM_TRAILER = 2


def checksum_definitions(length):
    if length % 2 or length <= SUM_TRAILER:
        raise ValueError(f"firmware length 0x{length:x} is too short or odd for the checksum layout")
    return [(0, length - SUM_TRAILER, "sum"), (1, length - NEGATIVE_SUM_TRAILER, "negative-sum")]


# Odyssey THR-A020 and RDX TJB-A220 images also carry runtime ROM CRCs. While
# running, the EPS recomputes a CRC-32/BZIP2 over each region and compares it
# with the big-endian word at the slot; a stale word passes the two checksums
# above but faults the EPS a second or two after it starts steering. Both
# images put the app at flash 0xC000 with a 0x74000 block; regions and slots
# are (start, end, slot) flash addresses.
ROM_CRC_SOFTWARE_IDS = (b'39990-THR', b'39990-TJB')
ROM_CRC_START, ROM_CRC_LENGTH = 0xc000, 0x74000
ROM_CRC_REGIONS = ((0x40000, 0x4ff60, 0x4ff7c), (0x60000, 0x6ff60, 0x6ff7c))


def _crc32_bzip2_table():
    table = []
    for i in range(256):
        c = i << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04c11db7) & 0xffffffff if c & 0x80000000 else (c << 1) & 0xffffffff
        table.append(c)
    return table


CRC32_BZIP2_TABLE = _crc32_bzip2_table()


def crc32_bzip2(data):
    c = 0xffffffff
    for b in data:
        c = ((c << 8) & 0xffffffff) ^ CRC32_BZIP2_TABLE[((c >> 24) ^ b) & 0xff]
    return c ^ 0xffffffff


def rom_crc_definitions(fw):
    """ROM CRC regions to check for this image, empty when it carries none."""
    ids = [value.value for value in fw.file_headers[3].values]
    if not any(i.startswith(prefix) for i in ids for prefix in ROM_CRC_SOFTWARE_IDS):
        return []
    block = fw.firmware_blocks[0]
    if (block["start"], block["length"]) != (ROM_CRC_START, ROM_CRC_LENGTH):
        raise ValueError(f"THR/TJB image must start at 0x{ROM_CRC_START:x} with length 0x{ROM_CRC_LENGTH:x}, "
                         f"got 0x{block['start']:x}/0x{block['length']:x}")
    return ROM_CRC_REGIONS


def validate_container(fw):
    """Check the headers the flasher reads."""
    headers = fw.file_headers
    if len(headers[2].values) != 1 or len(headers[2].values[0].value) != 1:
        raise ValueError("header 2 must hold exactly one 1-byte ECU address")
    ids, secrets = headers[3].values, headers[4].values
    if not ids or len(ids) != len(secrets):
        raise ValueError(f"header 3/4 mismatch: {len(ids)} software IDs, {len(secrets)} seed secrets")
    if any(len(s.value) != 6 for s in secrets):
        raise ValueError("seed secrets in header 4 must be 6 bytes")
    if len(fw.firmware_blocks) != 1:
        raise ValueError("exactly one firmware block is required")


def validate_firmware(fw):
    """Validate the container headers, both firmware checksums and any THR/TJB ROM CRCs."""
    validate_container(fw)
    length = fw.firmware_blocks[0]["length"]
    encrypted = fw.firmware_encrypted[0]
    if len(encrypted) != length:
        raise ValueError("firmware length incorrect")
    definitions = checksum_definitions(length)
    decrypted = bytes(DECRYPT_LOOKUP[b] for b in encrypted)
    for func, offset, label in definitions:
        stored = struct.unpack('!H', decrypted[offset:offset + 2])[0]
        words = struct.unpack(f'!{offset // 2}H', decrypted[:offset])
        calculated = (sum(words) * (-1 if func else 1)) & 0xffff
        if stored != calculated:
            raise ValueError(f"firmware checksum failed: {label} at 0x{offset:x}")
        print(f"  Firmware {label} checksum: PASS")
    start = fw.firmware_blocks[0]["start"]
    for region_start, region_end, slot in rom_crc_definitions(fw):
        stored = struct.unpack('!I', decrypted[slot - start:slot - start + 4])[0]
        calculated = crc32_bzip2(decrypted[region_start - start:region_end - start])
        if stored != calculated:
            raise ValueError(f"ROM CRC failed: [0x{region_start:x},0x{region_end:x}) at 0x{slot:x} "
                             f"stores {stored:08x}, image gives {calculated:08x}")
        print(f"  ROM CRC at 0x{slot:x}: PASS")


def check(path):
    from rwd_format.x5a import x5a
    print(f"\nChecking {path}")
    try:
        with open(path, 'rb') as stream:
            fw = x5a(stream.read())
        print("  Container and file checksum: PASS")
        validate_firmware(fw)
    except (OSError, ValueError) as e:
        print(f"  NOT VALIDATED: {e}")
        return False
    print("  Fully validated: PASS")
    return True


def main(argv=None):
    paths = sys.argv[1:] if argv is None else argv
    if not paths:
        print("Usage: python3 check_rwd.py <file.rwd> [file2.rwd ...]")
        return 1
    results = [check(path) for path in paths]
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
