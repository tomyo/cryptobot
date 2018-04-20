if [ ! -e cryptomkt ]; then
    git clone https://github.com/cryptomkt/cryptomkt-python.git cryptomkt
    cd cryptomkt
    > __init__.py
    pip2 install -r requirements.txt
    cd ..
else
    echo "Skipping the cloning and installing of cryptomkt repo. (cryptomkt folder already exists)"
fi
if [ ! -e api_keys.py ]; then
    echo 'api_key = "<add_your_key>"' > api_keys.py
    echo 'api_secret = "<add_your_key>"' >> api_keys.py
fi
echo 'Done!'
echo 'Remember adding your api keys to api_keys.py'