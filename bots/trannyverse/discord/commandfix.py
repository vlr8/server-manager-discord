import json, requests
import os
from dotenv import load_dotenv
load_dotenv()
COMMANDS_AUTHORIZATION = os.environ["COMMANDS_AUTHORIZATION"]


headers = {
    'Authorization': COMMANDS_AUTHORIZATION
}


# Get all application commands
def get_commands():
    resp = requests.get('https://discord.com/api/v8/applications/1128910064569303081/commands', headers=headers)
    return resp.json()


# Delete application command
def delete_command(command_id):
    resp = requests.delete(f'https://discord.com/api/v8/applications/1128910064569303081/commands/{command_id}', headers=headers)


def debug():
    # Delete all application commands
    commands = get_commands()
    for command in commands:
        print(command['id'])
        delete_command(command['id'])


if __name__ == '__main__':
    debug()
