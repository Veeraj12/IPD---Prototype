def get_signal_time(zone_a_count, zone_b_count):
    """
    Dynamic Traffic Controller based on ROI.
    Compares two lanes. The lane with higher volume gets Green, the other Red.
    """
    if zone_a_count == 0 and zone_b_count == 0:
        return {"zone_a": "Yellow (Idle)", "zone_b": "Yellow (Idle)"}

    # Decide who gets priority
    if zone_a_count >= zone_b_count:
        active, stopped = "zone_a", "zone_b"
        active_count = zone_a_count
    else:
        active, stopped = "zone_b", "zone_a"
        active_count = zone_b_count

    # Calculate green time purely based on congestion level
    if active_count >= 9:
        time = 60
    elif active_count >= 4:
        time = 30
    else:
        time = 15

    return {
        active: f"Green ({time}s)",
        stopped: "Red"
    }