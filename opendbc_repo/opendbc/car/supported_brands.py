"""Brands this fork supports. Every other brand is fingerprinted, logged and left in dashcam mode."""

# Acura platforms are part of the honda brand. Stock and modified EPS, stock and openpilot longitudinal are all
# supported; an unrecognised modified EPS is still forced to dashcam by the Honda interface itself.
SUPPORTED_BRANDS = frozenset({"honda"})


def brand_supported(brand: str) -> bool:
  return brand in SUPPORTED_BRANDS


def limit_to_supported_brands(CP):
  """Only ever adds dashcam: a platform the interface already put in dashcam stays there."""
  if not brand_supported(CP.brand):
    CP.dashcamOnly = True
  return CP
