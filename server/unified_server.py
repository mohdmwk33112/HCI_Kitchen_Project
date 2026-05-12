import os
import conn
from conn import connect_to_server, receive_messages
from core.vision_manager import VisionManager
from cooking.cooking_session import send_recipe

# ── Configuration ──────────────────────────────────────────────────────────
PEOPLE_DIR = os.path.join("face", "people")
HOST = "0.0.0.0"
PORT = 65434

def handle_client():
    # ── 1. Accept the client connection ───────────────────────────────────
    conn_obj, server = connect_to_server(HOST, PORT)
    print("Unified connection established.")

    # ── 2. Start the Continuous Vision Manager ─────────────────────────────
    # VisionManager runs cv2.VideoCapture(0) continuously.
    # Starts in 'LOGIN' state, automatically switches to 'GESTURES' upon success.
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
                vision.set_state("LOGIN")
                conn_obj.sendall("logout_success\n".encode("utf-8"))

            elif cmd == "START_GESTURES":
                # With continuous vision, gestures start automatically after login.
                # But client might send this as a confirmation.
                print("Gestures mode confirmed by client.")
                vision.set_state("GESTURES")
                conn_obj.sendall("gestures_started\n".encode("utf-8"))

            # ── Recipe / Cooking Session ───────────────────────────────
            elif cmd == "RECIPE_ID":
                send_recipe(conn_obj, parts)

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
