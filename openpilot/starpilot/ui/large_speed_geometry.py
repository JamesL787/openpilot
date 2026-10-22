"""Speed group geometry shared by rendering, input and layout metadata."""

WIDTH = 488
MAX_ROW_HEIGHT = 132
LIMIT_ROW_HEIGHT = MAX_ROW_HEIGHT
CARD_HEIGHT = MAX_ROW_HEIGHT
ACTION_WIDTH = 576
ACTION_HEIGHT = 160
ACTION_X = 100
ACTION_Y = 248
GAP = 8
SOURCE_ROW_HEIGHT = 76
PADDING = 24

LIMIT_RECTS = {'large': (272, 94, 292, 124), 'compact': (158, 10, 264, 82)}
ACTION_BOUNDS = {
  'large': ((100, 248, 372, 408), (404, 248, 676, 408)),
  'compact': ((16, 118, 224, 222), (248, 118, 456, 222)),
}
ACTION_TEXT = {'large': (64, 320), 'compact': (50, 146)}


def card_height(mode):
  return CARD_HEIGHT if mode == 'split' else LIMIT_ROW_HEIGHT if mode == 'limit_only' else MAX_ROW_HEIGHT


def sources_extent(document):
  """Extra height the cruise widget takes for speed-limit sources: a row in the card, or a small card of its own below."""
  if document.get('speedSources') is not True:
    return 0
  return GAP + SOURCE_ROW_HEIGHT if document.get('speedSourcesCard') is True else SOURCE_ROW_HEIGHT
