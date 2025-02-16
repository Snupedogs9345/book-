import smtplib

from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr





def send_mes(msg):
    print("зашел")
    #-------------------------#
    sender = "prostor@prostor-dev.store"#codered_it@coderedit.ru
    password = "RostProsto_491"

    server = smtplib.SMTP("smtp.beget.com", 2525)
    server.starttls()
    #-------------------------#

    user_from = 'snupedogs@mail.ru'
    try:
        print('nenene')
        server.login(sender, password)
        msg = MIMEText(f"{msg}", "html","utf-8")

        msg["From"] = formataddr((str(Header("ПРОСТОР", "utf-8")), sender))
        msg["To"] = 'snupedogs@mail.ru'#user_from  # sender


        msg["Subject"] = 'ПРОСТОР - Разработка'
        server.sendmail(sender, user_from, msg.as_string())
        print("The message was sent successfully!")

    except Exception as _ex:
        print(f"{_ex}\nCheck your login or password please!")


msg = 'Привет!'
send_mes(msg)
