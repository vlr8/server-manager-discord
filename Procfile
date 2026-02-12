# Railway Procfile - each line becomes a separate worker service.
# All three share the same persistent volume mounted at /data
# (set DATA_DIR=/data in Railway environment variables).
#
# To run only specific bots, comment out the others.
# Vision/CLIP features are disabled on Railway (no GPU).

# persona: python -m bots.persona.persona_bot
trannyverse: python -m bots.trannyverse.bot1
protector: python -m bots.protector.server_helper
