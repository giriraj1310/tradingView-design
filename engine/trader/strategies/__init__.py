from .trend import TrendFollowing

REGISTRY = {
    "trend": TrendFollowing,
}


def build(name: str, **kwargs):
    if name not in REGISTRY:
        raise ValueError(f"Unknown strategy '{name}'. Known: {list(REGISTRY)}")
    return REGISTRY[name](**kwargs)
