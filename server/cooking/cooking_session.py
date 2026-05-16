"""
cooking_session.py — Recipe & session logic for the Kitchen Assistant server.
Uses the new ERD schema via db.py.

Protocol (all messages newline-terminated UTF-8):
  Client → Server:
    RECIPE_ID;<id>        request recipe
    CONFIRM               user confirmed recipe, start step-by-step
    NEXT                  advance to next step
    LOG;<type>;<json>     log an interaction event
    EVAL;<time>;<errors>;<nasa_score>;<feedback>   submit evaluation

  Server → Client:
    <title>;<scenario>;<ingredient1_json>;...    recipe header
    step;<number>;<total>;<instruction>          individual step
    session_done                                 all steps complete
    error;<reason>                               something went wrong
"""

import json
from db import get_recipe, start_session, log_interaction, save_evaluation
from conn import receive_messages


# ─────────────────────────────────────────────
#  Recipe delivery
# ─────────────────────────────────────────────
def send_recipe(conn, parts, vision, user_id=None):
    """
    Called when client sends RECIPE_ID;<id>.
    parts = ["RECIPE_ID", "<id>"]
    """
    try:
        recipe_id = int(parts[1])
    except (IndexError, ValueError):
        conn.sendall("error;invalid_recipe_id\n".encode("utf-8"))
        return

    recipe = get_recipe(recipe_id)
    if not recipe:
        conn.sendall("error;recipe_not_found\n".encode("utf-8"))
        return

    # ── Build header: title;scenario;[ingredient objects as JSON]
    ingredients = recipe["ingredients_json"]  # already parsed list
    header = f"{recipe['title']};{recipe['scenario'] or ''};"
    for ing in ingredients:
        # Each ingredient is a dict: {"name":..., "quantity":..., "unit":...}
        if isinstance(ing, dict):
            header += f"{ing.get('name','')};{ing.get('quantity','')};{ing.get('unit','')};"
        else:
            header += f"{ing};"

    conn.sendall(header.encode("utf-8"))

    # ── Wait for client confirmation before sending steps
    while True:
        confirm = receive_messages(conn)
        if not confirm: return
        cmd = confirm.strip().upper()
        if cmd == "CONFIRM": break
        if cmd == "CANCEL": 
            print("[CookingSession] Recipe cancelled by user.")
            return
        if cmd == "LOGOUT":
            side = vision.set_state("LOGIN")
            conn.sendall(f"logout_success;{side}\n".encode("utf-8"))
            return

    # ── Create a session record via VisionManager to enable shared tracking
    session_id = vision.start_new_session(recipe_id=recipe_id, 
                                          scenario=recipe.get("scenario"))

    _send_steps(conn, recipe["steps_json"], session_id, vision)


def _send_steps(conn, steps, session_id, vision):
    """
    Sends steps with support for NEXT and PREV navigation.
    """
    total = len(steps)
    current_step = 0 # 0-indexed

    while current_step < total:
        instruction = steps[current_step]
        msg = f"step;{current_step + 1};{total};{instruction}"
        conn.sendall((msg + "\n").encode("utf-8"))

        # Wait for navigation or other commands
        while True:
            cmd_raw = receive_messages(conn)
            if not cmd_raw:
                return

            cmd_parts = cmd_raw.split(";", 2)
            cmd = cmd_parts[0].upper()

            if cmd == "NEXT" or cmd == "SWIPE_RIGHT":
                current_step += 1
                break # break inner loop to send next step

            elif cmd == "PREV" or cmd == "SWIPE_LEFT":
                if current_step > 0:
                    current_step -= 1
                    break # break inner loop to send previous step
                else:
                    # Already at first step, just re-send it to confirm
                    break
            
            elif cmd == "CANCEL":
                print("[CookingSession] Session cancelled during steps.")
                return

            elif cmd == "LOGOUT":
                print("[CookingSession] Logout requested during session.")
                side = vision.set_state("LOGIN")
                conn.sendall(f"logout_success;{side}\n".encode("utf-8"))
                return 

            elif cmd == "LOG" and len(cmd_parts) >= 3:
                itype = cmd_parts[1]
                try:
                    data = json.loads(cmd_parts[2])
                except Exception:
                    data = {"raw": cmd_parts[2]}
                log_interaction(session_id, itype, data)

            elif cmd == "EMOTION" and len(cmd_parts) >= 2:
                emotion = cmd_parts[1].lower()
                # If negative emotion detected, simplify/encourage the current step
                if emotion in ["angry", "sad", "disgust", "fear"]:
                    print(f"[CookingSession] Adaptive Support: detected {emotion}. Simplifying step.")
                    support_msg = f" (Focus on this part only: {instruction.split('.')[0]}. You've got this!)"
                    adaptive_msg = f"step;{current_step + 1};{total};{instruction}{support_msg}"
                    conn.sendall((adaptive_msg + "\n").encode("utf-8"))

            elif cmd == "EVAL" and len(cmd_parts) >= 2:
                _handle_eval(conn, session_id, cmd_raw)
                return

    # All steps sent
    conn.sendall("session_done\n".encode("utf-8"))


def _handle_eval(conn, session_id, raw):
    """
    Parses: EVAL;<task_time_sec>;<errors>;<nasa_tlx_score>;<feedback>
    """
    parts = raw.split(";")
    try:
        task_time  = int(parts[1])   if len(parts) > 1 else None
        errors     = int(parts[2])   if len(parts) > 2 else None
        nasa_score = float(parts[3]) if len(parts) > 3 else None
        feedback   = parts[4]        if len(parts) > 4 else None
    except (ValueError, IndexError):
        task_time = errors = nasa_score = feedback = None

    save_evaluation(session_id, task_time, errors, nasa_score, feedback)
    conn.sendall("eval_saved\n".encode("utf-8"))
