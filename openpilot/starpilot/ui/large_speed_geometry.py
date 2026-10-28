"""Speed group geometry shared by rendering, input and layout metadata."""

import math

WIDTH = 488
MAX_ROW_HEIGHT = 132
LARGE_SIGN_SCALE = 1.25
LIMIT_ROW_HEIGHT = 168
CARD_HEIGHT = LIMIT_ROW_HEIGHT
ACTION_WIDTH = 308
ACTION_HEIGHT = 168
ACTION_X = 112
ACTION_Y = 267
GAP = 8
SOURCE_ROW_HEIGHT = 76
PADDING = 24

LIMIT_RECTS = {'large': (318, 75, 148, 165), 'compact': (330, 20, 118, 132)}
ACTION_BOUNDS = {
  'large': ((112, ACTION_Y, 420, ACTION_Y + 80), (112, ACTION_Y + 88, 420, ACTION_Y + ACTION_HEIGHT)),
  'compact': ((146, 44, 330, 102), (146, 106, 330, 164)),
}
ACTION_TEXT_SIZE = {'large': 64, 'compact': 48}

# Match physical touch size: the large display is ~402.5 PPI; compact is 300 PPI.
CONFIRMATION_SCALE = {'large': math.hypot(2160, 1080) / 6 / 300, 'compact': 1.0}
CONFIRMATION_HEIGHT = 152
CONFIRMATION_HEADER = 40
CONFIRMATION_BUTTON = 144
CONFIRMATION_GAP = 8
CONFIRMATION_PADDING = 8


def confirmation_bounds(profile, x, y, *, opened=False):
  scale = CONFIRMATION_SCALE[profile]
  width = 2 * CONFIRMATION_PADDING + 2 * CONFIRMATION_BUTTON + CONFIRMATION_GAP if opened else 240
  left = x + 172 if profile == 'large' else x + 130 - width * scale
  return left, y - 12, left + width * scale, y - 12 + CONFIRMATION_HEIGHT * scale


def confirmation_buttons(profile, bounds):
  left, top, _, bottom = bounds
  scale = CONFIRMATION_SCALE[profile]
  return tuple((left + (CONFIRMATION_PADDING + x) * scale, top + CONFIRMATION_HEADER * scale,
                left + (CONFIRMATION_PADDING + x + CONFIRMATION_BUTTON) * scale, bottom)
               for x in (0, CONFIRMATION_BUTTON + CONFIRMATION_GAP))


def confirmation_footprint(profile):
  left, top, right, bottom = confirmation_bounds(profile, 0, 0, opened=True)
  return {'x': left, 'y': top, 'width': right - left, 'height': bottom - top}


SOURCE_TOP = math.ceil(confirmation_bounds('large', 0, 0)[3]) + GAP


def card_height(mode):
  return CARD_HEIGHT if mode == 'split' else LIMIT_ROW_HEIGHT if mode == 'limit_only' else MAX_ROW_HEIGHT


def sources_extent(document):
  """Extra height the cruise widget takes for speed-limit sources: a row in the card, or a small card of its own below."""
  if document.get('speedSources') is not True:
    return 0
  return SOURCE_TOP - CARD_HEIGHT + SOURCE_ROW_HEIGHT + (GAP if document.get('speedSourcesCard') is True else 0)
