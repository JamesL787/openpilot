"""Speed group geometry shared by rendering, input and layout metadata."""

WIDTH = 488
MAX_ROW_HEIGHT = 132
LARGE_SIGN_SCALE = .95
LIMIT_ROW_HEIGHT = 168
CARD_HEIGHT = LIMIT_ROW_HEIGHT
ACTION_WIDTH = 576
ACTION_HEIGHT = 148
ACTION_X = 100
ACTION_Y = 296
GAP = 8
SOURCE_ROW_HEIGHT = 76
PADDING = 24

LIMIT_RECTS = {'large': (272, 75, 113, 126), 'compact': (330, 20, 118, 132)}
ACTION_BOUNDS = {
  'large': ((100, ACTION_Y, 372, ACTION_Y + ACTION_HEIGHT), (404, ACTION_Y, 676, ACTION_Y + ACTION_HEIGHT)),
  'compact': ((128, 182, 296, 240), (308, 182, 476, 240)),
}
ACTION_TEXT = {'large': (64, ACTION_Y + 72), 'compact': (48, 213)}


def card_height(mode):
  return CARD_HEIGHT if mode == 'split' else LIMIT_ROW_HEIGHT if mode == 'limit_only' else MAX_ROW_HEIGHT


def sources_extent(document):
  """Extra height the cruise widget takes for speed-limit sources: a row in the card, or a small card of its own below."""
  if document.get('speedSources') is not True:
    return 0
  return GAP + SOURCE_ROW_HEIGHT if document.get('speedSourcesCard') is True else SOURCE_ROW_HEIGHT
