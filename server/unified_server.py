import os
import conn
import json
from conn import connect_to_server, receive_messages
from core.vision_manager import VisionManager
from cooking.cooking_session import send_recipe

# ── Configuration ──────────────────────────────────────────────────────────
PEOPLE_DIR = os.path.join("face", "people")
HOST = "0.0.0.0"
PORT = 65434

def handle_client():
    # ── 0. Initialize Database ──────────────────────────────────────────
    import db
    db.init_db()
    db.sync_users_from_files(PEOPLE_DIR)

    # ── 1. Accept the client connection ───────────────────────────────────
    conn_obj, server = connect_to_server(HOST, PORT)
    print("Unified connection established.")

    # ── 2. Start the Continuous Vision Manager ─────────────────────────────
    vision = VisionManager(PEOPLE_DIR, conn_obj)
    vision.start()

    try:
        # ── 3. MAIN COMMAND LOOP ───────────────────────────────────────────
        while True:
            msg = receive_messages(conn_obj)
            if not msg:
                print("Client disconnected.")
                break

            parts = msg.split(";")
            cmd = parts[0].upper()

            # ── Session Control ────────────────────────────────────────
            if cmd == "LOGOUT":
                print("Client requested logout.")
                side = vision.set_state("LOGIN")
                conn_obj.sendall(f"logout_success;{side}\n".encode("utf-8"))

            elif cmd == "START_GESTURES":
                print("Gestures mode confirmed by client.")
                vision.set_state("GESTURES")
                conn_obj.sendall("gestures_started\n".encode("utf-8"))

            elif cmd == "CAPTURE_FACE":
                if len(parts) > 1:
                    name = parts[1]
                    print(f"[Server] Capture requested for: {name}")
                    vision.capture_name = name
                    vision.capture_pending = True
                else:
                    conn_obj.sendall("error;missing_name\n".encode("utf-8"))

            elif cmd == "LIST_USERS":
                import glob
                files = glob.glob(os.path.join(PEOPLE_DIR, "*.jpg"))
                names = [os.path.splitext(os.path.basename(f))[0] for f in files]
                resp = "users_list;" + ";".join(names) + "\n"
                conn_obj.sendall(resp.encode("utf-8"))

            elif cmd == "DELETE_USER":
                if len(parts) > 1:
                    name = parts[1]
                    path = os.path.join(PEOPLE_DIR, f"{name}.jpg")
                    if os.path.exists(path):
                        os.remove(path)
                        print(f"[Server] Deleted user: {name}")
                        vision.face_handler.load_known_faces() # Reload encoding DB
                        conn_obj.sendall("delete_success\n".encode("utf-8"))
                    else:
                        conn_obj.sendall("error;user_not_found\n".encode("utf-8"))
                else:
                    conn_obj.sendall("error;missing_name\n".encode("utf-8"))

            # ── Circular Menu State Control ────────────────────────────
            elif cmd == "MENU_OPEN":
                print("[Server] Circular menu opened — suppressing camera gestures.")
                vision.set_state("CIRCULAR_MENU")
                conn_obj.sendall("menu_open_ack\n".encode("utf-8"))

            elif cmd == "MENU_CLOSED":
                print("[Server] Circular menu closed — resuming camera gestures.")
                vision.set_state("GESTURES")
                conn_obj.sendall("menu_closed_ack\n".encode("utf-8"))

            # ── Recipe / Cooking Session ───────────────────────────────
            elif cmd == "GET_SUGGESTION":
                from datetime import datetime
                hour = datetime.now().hour
                if 5 <= hour < 12: sugg_id, sugg_name = 1, "Omelette"
                elif 12 <= hour < 21: sugg_id, sugg_name = 2, "Pizza"
                else: sugg_id, sugg_name = 4, "Cake"
                conn_obj.sendall(f"suggestion;{sugg_id};{sugg_name}\n".encode("utf-8"))

            elif cmd == "RECIPE_ID":
                # Note: send_recipe takes over the receive_messages loop until recipe is done
                send_recipe(conn_obj, parts, vision)
                # After recipe is done, we return here to the main loop

            # ── Passive/Global Commands (Acknowledge to avoid errors) ──
            elif cmd == "LOG":
                # Already handled inside send_recipe for active sessions,
                # but if sent globally, we just acknowledge or log to console.
                print(f"[Server] Global Log: {parts[1] if len(parts) > 1 else ''}")
            
            elif cmd == "NEXT":
                # Handled inside send_recipe's _send_steps loop.
                # If it reaches here, no recipe is active.
                print("[Server] NEXT received but no recipe session is active.")

            # ── Graceful shutdown ──────────────────────────────────────
            elif cmd == "Q":
                break

            else:
                print(f"Unknown command: {cmd}")

    except Exception as e:
        print(f"Session error: {e}")
    finally:
        vision.running = False
        conn_obj.close()
        server.close()
        print("Connection closed.")


if __name__ == "__main__":
    handle_client()
