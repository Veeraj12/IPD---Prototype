import time

# ==========================================================
# GLOBAL STATE
# ==========================================================
lane_wait_time = {}
current_green = None
signal_state = "GREEN"
last_switch_time = time.time()

# timings
MIN_GREEN = 10
MAX_GREEN = 25
YELLOW_TIME = 3
STARVATION_LIMIT = 30

# weights
W_DENSITY = 0.70
W_WAIT = 0.30


# ==========================================================
# INIT
# ==========================================================
def init_lanes(n):
    global lane_wait_time

    lane_wait_time = {i: 0 for i in range(n)}


# ==========================================================
# SCORE FUNCTION
# ==========================================================
def _score_lane(i, density):
    """
    density should be 0 to 1 range ideally
    """
    wait_norm = min(lane_wait_time[i] / STARVATION_LIMIT, 1.0)

    return (
        W_DENSITY * density +
        W_WAIT * wait_norm
    )


# ==========================================================
# MAIN CONTROLLER
# ==========================================================
def get_signal_state(density_map):
    """
    density_map = {0:0.15, 1:0.63}
    """

    global current_green
    global signal_state
    global last_switch_time
    global lane_wait_time

    now = time.time()

    if not lane_wait_time:
        init_lanes(len(density_map))

    # ------------------------------------------------------
    # starvation override
    # ------------------------------------------------------
    starved_lane = None

    for i, wt in lane_wait_time.items():
        if wt >= STARVATION_LIMIT:
            starved_lane = i
            break

    # ------------------------------------------------------
    # choose best next lane
    # ------------------------------------------------------
    if starved_lane is not None:
        next_lane = starved_lane
    else:
        scores = {
            i: _score_lane(i, density_map[i])
            for i in density_map
        }

        next_lane = max(scores, key=scores.get)

    elapsed = now - last_switch_time

    # ======================================================
    # GREEN STATE
    # ======================================================
    if signal_state == "GREEN":

        if current_green is None:
            current_green = next_lane
            last_switch_time = now

        else:
            active_density = density_map.get(current_green, 0)

            # hold minimum green
            if elapsed < MIN_GREEN:
                pass

            else:
                # if another lane deserves priority OR lane empty
                if (
                    next_lane != current_green and
                    (
                        density_map[next_lane] > active_density * 1.15
                        or active_density < 0.05
                        or elapsed >= MAX_GREEN
                    )
                ):
                    signal_state = "YELLOW"
                    last_switch_time = now

                elif elapsed >= MAX_GREEN:
                    signal_state = "YELLOW"
                    last_switch_time = now

    # ======================================================
    # YELLOW STATE
    # ======================================================
    elif signal_state == "YELLOW":

        if elapsed >= YELLOW_TIME:

            if starved_lane is not None:
                current_green = starved_lane
            else:
                current_green = next_lane

            signal_state = "GREEN"
            last_switch_time = now

    # ======================================================
    # UPDATE WAIT TIMES
    # ======================================================
    for i in lane_wait_time:

        if i == current_green and signal_state == "GREEN":
            lane_wait_time[i] = 0
        else:
            lane_wait_time[i] += 1

    remaining = 0

    elapsed = now - last_switch_time

    if signal_state == "GREEN":
        remaining = max(int(MIN_GREEN - elapsed), 0)

    elif signal_state == "YELLOW":
        remaining = max(int(YELLOW_TIME - elapsed), 0)

    return current_green, signal_state, remaining