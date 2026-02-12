# Railway Procfile - each line becomes a separate worker service.
# All three share the same persistent volume mounted at /data
# (set DATA_DIR=/data in Railway environment variables).
#
# To run only specific bots, comment out the others.
# Vision/CLIP features are disabled on Railway (no GPU).


# standalone script to run all 3
worker: python run_all.py