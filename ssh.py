import os
import socket
import sys
import threading
from time import sleep

import paramiko

from settings import (EXECUTION_TIME_LIMIT, HONEYPOT_SSH_PORT,
                      HONEYPOT_USER_NAME, KEYFILE_PATH, TMP_SPECIMEN_DIR,
                      VM_USER_NAME)


def send_file(client, filepath):
    """SFTPでファイルの送信"""

    filename = os.path.basename(filepath)
    try:
        sftp_connection = client.open_sftp()
        vm_path = f'/home/{VM_USER_NAME}/{filename}'
        sftp_connection.put(filepath, vm_path)
        sftp_connection.chmod(vm_path, 0o755)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        sys.exit(1)


def connect_and_send_file(ip_addr, filepath):
    """検体の送信だけを行う．実行はしない"""

    with paramiko.SSHClient() as client:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip_addr, username=VM_USER_NAME, key_filename=KEYFILE_PATH, timeout=1)
        send_file(client, filepath)


def send_and_execute_file(filepath, ip_addr):
    """ファイルを送信して実行し、結果を得る関数。

    Args:
        filepath (str): 送信、実行するファイルのフルパス
        ip_addr (str): 送信先のIPアドレス

    Returns:
        stdout_text: 標準出力をutf-8でデコードしたもの
        stderr_text: 標準エラー出力をutf-8でデコードしたもの
    """

    filename = os.path.basename(filepath)
    with paramiko.SSHClient() as client:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip_addr, username=VM_USER_NAME, key_filename=KEYFILE_PATH, timeout=1)

        send_file(client, filepath)

        print(f"command: ./{filename}")

        # 別のスレッドで、実行時間制限だけsleepする関数を実行する。
        # これにより、もしexec_command関数で実行したコマンドが時間内に終了しても、
        # 制限時間までスレッドがjoinするのを待つことで毎回一定時間パケットキャプチャするようにしている。
        thread = threading.Thread(target=execution_time_limit, args=(EXECUTION_TIME_LIMIT,))
        thread.start()

        try:
            _, stdout, stderr = client.exec_command(f"./{filename}", timeout=EXECUTION_TIME_LIMIT)

            print("\n****************stdout*****************")
            for line in stdout:
                print(line, end="")

            print("\n****************stderr*****************")
            for line in stderr:
                print(line, end="")
        except socket.timeout:
            print("\n実行時間制限\n")
        else:
            returncode = stdout.channel.recv_exit_status()
            print(f"\n実行終了 return code = {returncode}\n")
        finally:
            thread.join()


def execution_time_limit(time):
    sleep(time)


def wait_until_receive(local_dir_path: str, remote_dir_path: str, ip_addr: str):
    """SSHで指定されたIPアドレスとコネクションを張り，指定されたパスを監視する．ファイルを発見したら受信して削除し，そのパスを返す．

    Args:
        local_dir_path (str): 受信するローカルのディレクトリ
        remote_dir_path (str): 監視するリモートのディレクトリ
        ip_addr (str): 監視するホストのIPアドレス

    Returns:
        received_filepath (str): 受信したファイルのパス

    Notes:
        remote_dir_pathに読み書き実行権限が必要
    """

    with paramiko.SSHClient() as client:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip_addr, port=HONEYPOT_SSH_PORT, username=HONEYPOT_USER_NAME, key_filename=KEYFILE_PATH, timeout=1)
        print("接続完了")
        with client.open_sftp() as sftpconn:
            specimen_list = sftpconn.listdir(remote_dir_path)
            while not specimen_list:
                print("No specimen found")
                sleep(10)
                specimen_list = sftpconn.listdir(remote_dir_path)
            else:
                specimen = specimen_list[0]
                print(f"Transferring {specimen}")
                remote_specimen_path = os.path.join(remote_dir_path, specimen)
                local_specimen_path = os.path.join(local_dir_path, specimen)
                sftpconn.get(remote_specimen_path, local_specimen_path)
                sftpconn.remove(remote_specimen_path)
                return local_specimen_path


if __name__ == "__main__":
    from settings import HONEYPOT_IP_ADDR, HONEYPOT_SPECIMEN_DIR
    wait_until_receive(TMP_SPECIMEN_DIR, HONEYPOT_SPECIMEN_DIR, HONEYPOT_IP_ADDR)
