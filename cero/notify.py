"""Bandeja de avisos: por defecto sólo informa; --send requiere activación explícita."""
import argparse
from cero.db import connect,unpack,now
from cero.telegram import armed,send_deal


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--send',action='store_true');args=parser.parse_args()
    if args.send and not armed():raise SystemExit('Telegram está desactivado o faltan credenciales. No se ha enviado nada.')
    c=connect()
    try:
        rows=c.execute('SELECT n.id notification_id,d.* FROM notifications n JOIN deals d ON d.id=n.deal_id WHERE n.sent_at IS NULL ORDER BY n.id LIMIT 100').fetchall()
        print(str(len(rows))+' avisos en bandeja. '+('Envío activado.' if args.send else 'Sólo lectura: no se envían mensajes.'))
        if args.send:
            for row in rows:
                if send_deal(unpack(row)):c.execute('UPDATE notifications SET sent_at=? WHERE id=?',(now(),row['notification_id']));c.commit()
    finally:c.close()


if __name__=='__main__':main()
