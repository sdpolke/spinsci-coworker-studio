from hypothesis import HealthCheck, settings

settings.register_profile(
    "langgraph_contract",
    max_examples=100,
    deadline=None,
    suppress_health_check=(HealthCheck.too_slow,),
)
settings.load_profile("langgraph_contract")
