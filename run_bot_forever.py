"""Supervisor simple para mantener zanni_quant_bot.py corriendo.

Reinicia el bot si el proceso termina por error. No reemplaza systemd: si el
computador o la sesion se apagan, hay que lanzarlo de nuevo.
"""
import subprocess
import sys
import time


RESTART_DELAY_SECONDS = 5


def main() -> None:
    while True:
        started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[supervisor] starting bot at {started_at}", flush=True)
        process = subprocess.Popen([sys.executable, "zanni_quant_bot.py"])
        return_code = process.wait()
        stopped_at = time.strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"[supervisor] bot exited rc={return_code} at {stopped_at}; "
            f"restart in {RESTART_DELAY_SECONDS}s",
            flush=True,
        )
        time.sleep(RESTART_DELAY_SECONDS)


if __name__ == "__main__":
    main()
