from bottle import Bottle, static_file
import subprocess

app = Bottle()

@app.route('/')
def root():
    return static_file('hello.html', root='./static')

@app.route('/hello.html')
def hello():
    return static_file('hello.html', root='./static')

@app.route('/test')
def test():
    result = subprocess.run(['./test.sh'], capture_output=True, text=True)
    return f'<pre>{result.stdout}</pre>'

@app.route('/sendtest')
def sendtest():
    msg = "Subject: T9AMAIL test send\n\nThis is a trivial end-to-end send test."
    result = subprocess.run(
        ['msmtp', '-a', 'posteo', '--', 'simon.kearns@posteo.net'],
        input=msg, capture_output=True, text=True
    )
    status = 'sent OK' if result.returncode == 0 else f'FAILED: {result.stderr}'
    return f'<pre>{status}</pre>'

app.run(host='0.0.0.0', port=80)
