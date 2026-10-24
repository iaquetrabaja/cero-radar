"""Inicio de sesión de Windows, sin cambiar políticas de seguridad del sistema."""
import os
from pathlib import Path
import sys


def main():
    if os.name!='nt':raise SystemExit('Usa un servicio systemd o tu gestor de procesos para iniciar CERO al arrancar.')
    script=Path(__file__).resolve().with_name('supervisor.py')
    python=Path(sys.executable).with_name('pythonw.exe')
    if not python.exists():raise SystemExit('No se ha encontrado pythonw.exe en esta instalación de Python.')
    startup=Path(os.environ['APPDATA'])/'Microsoft'/'Windows'/'Start Menu'/'Programs'/'Startup'
    target=startup/'CERO Radar.vbs'
    command=f'"{python}" "{script}"'
    target.write_text('CreateObject("WScript.Shell").Run "'+command.replace('"','""')+'", 0, False\n',encoding='utf-16')
    print('Inicio automático instalado. CERO se reanuda al iniciar sesión en Windows.')


if __name__=='__main__':main()
