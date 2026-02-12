import datetime
import re
import time

import interactions
from interactions import slash_command, SlashContext, OptionType, slash_option, listen, Intents, component_callback, \
    Modal, ShortText, ParagraphText, ModalContext, SlashCommandChoice, Permissions, Button, ButtonStyle
from interactions.api.events import *
import matplotlib.pyplot as plt
import seaborn as sns
from pprint import pprint
import traceback
import asyncio
import helpers
import urban
import yandex
import json
import profanity
import env
import requests,json
import base64

headers = {"Authorization": f"Bot {env.bot_token}"}
boymoder_guild = 1086159781284298822
tranners_guild = 1158203871554961579
# client = interactions.Client(token=env.bot_token, default_scope=boymoder_guild,
#                              # intents=Intents.GUILDS | Intents.GUILD_MEMBERS | Intents.GUILD_MESSAGES | Intents.GUILD_MESSAGE_REACTIONS | Intents.MESSAGE_CONTENT | Intents.DIRECT_MESSAGES | Intents.DIRECT_MESSAGE_REACTIONS
#                              intents=Intents.ALL
#                              )
#
#
# # Check if the bot is ready
# @interactions.listen()
# async def on_startup():
#     print(f"We're online!")

# client.start()


def add_emoji(emoji):
    image_type = "png" if not emoji['animated'] else "gif"

    resp = requests.get(f'https://cdn.discordapp.com/emojis/{emoji["id"]}.{image_type}', timeout=5)
    image_data = resp.content
    base64_encoded = base64.b64encode(image_data).decode("utf-8")

    # Now add the emoji to the new server
    resp = requests.post(f"https://discord.com/api/v8/guilds/{tranners_guild}/emojis", headers=headers, json={
        "name": emoji["name"],
        "image": f"data:image/{image_type};base64," + base64_encoded
    })
    print(resp.status_code)
    if resp.status_code == 429:
        print(f"Retrying in {resp.json()['retry_after']} seconds")
        time.sleep(resp.json()["retry_after"])
        add_emoji(emoji)

    elif resp.status_code != 201:
        return False
        
    elif resp.status_code == 201:
        return True



def main():
    # open emojis file json
    with open("emojis.json", "r") as f:
        emojis = json.load(f)
    print(f'Loaded {len([e for e in emojis if not e["animated"]])} static emojis and {len([e for e in emojis if e["animated"]])} animated emojis')
    
    # get all emojis from discord and add them to the new server (tranners)
    for emoji in emojis:
        try:
            result = add_emoji(emoji)
            if not result:
                print("Failed to add emoji, url:", f'https://cdn.discordapp.com/emojis/{emoji["id"]}.{"png" if not emoji["animated"] else "gif"}')
                exit(0)
                
            else:
                print(f"Added emoji {emoji['name']} to the new server")
                # Remove the emoji from the list so we don't try to add it again
                emojis.remove(emoji)
                # Save the updated list
                with open("emojis.json", "w") as f:
                    json.dump(emojis, f, indent=4)
    
        except:
            print(traceback.format_exc())


if __name__ == '__main__':
    main()