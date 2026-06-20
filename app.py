import sqlite3
import uuid
from datetime import datetime
from flask import Flask, request, render_template, redirect, url_for, g
from user_agents import parse

class Database:
    """Classe para gerenciar a conexão com o banco de dados"""
    
    def __init__(self, database_path='honey_tokens.db'):
        self.database_path = database_path
        self._database = None
    
    def get_db(self):
        if self._database is None:
            self._database = sqlite3.connect(self.database_path)
            self._database.row_factory = sqlite3.Row
        return self._database
    
    def close(self):
        if self._database is not None:
            self._database.close()
            self._database = None
    
    def init_db(self):
        db = self.get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS accesses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id TEXT NOT NULL,
                ip TEXT,
                user_agent TEXT,
                browser TEXT,
                os TEXT,
                device TEXT,
                referer TEXT,
                language TEXT,
                screen_resolution TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (token_id) REFERENCES tokens (id)
            )
        ''')
        db.commit()

class Token:
    """Classe para representar um token honey"""
    
    def __init__(self, db, token_id=None, name=None, description=None, created_at=None):
        self.db = db
        self.id = token_id
        self.name = name
        self.description = description
        self.created_at = created_at or datetime.now().isoformat()
    
    def save(self):
        """Salva o token no banco de dados"""
        if not self.id:
            self.id = str(uuid.uuid4())[:8]
        
        self.db.execute(
            'INSERT INTO tokens (id, name, description, created_at) VALUES (?, ?, ?, ?)',
            (self.id, self.name, self.description, self.created_at)
        )
        self.db.commit()
        return self.id
    
    @staticmethod
    def find_by_id(db, token_id):
        """Busca um token pelo ID"""
        result = db.execute('SELECT * FROM tokens WHERE id = ?', (token_id,)).fetchone()
        if result:
            return Token(db, result['id'], result['name'], result['description'], result['created_at'])
        return None
    
    @staticmethod
    def find_all(db):
        """Busca todos os tokens"""
        tokens = db.execute('SELECT * FROM tokens ORDER BY created_at DESC').fetchall()
        return [Token(db, t['id'], t['name'], t['description'], t['created_at']) for t in tokens]
    
    def delete(self):
        """Deleta o token e todos os seus acessos"""
        self.db.execute('DELETE FROM accesses WHERE token_id = ?', (self.id,))
        self.db.execute('DELETE FROM tokens WHERE id = ?', (self.id,))
        self.db.commit()
    
    def get_access_count(self):
        """Retorna o número de acessos deste token"""
        result = self.db.execute('SELECT COUNT(*) as count FROM accesses WHERE token_id = ?', 
                                (self.id,)).fetchone()
        return result['count']
    
    def get_last_access(self):
        """Retorna o último acesso deste token"""
        return self.db.execute('SELECT * FROM accesses WHERE token_id = ? ORDER BY timestamp DESC LIMIT 1',
                              (self.id,)).fetchone()

class Access:
    """Classe para representar um acesso a um token"""
    
    def __init__(self, db, token_id, client_info):
        self.db = db
        self.token_id = token_id
        self.ip = client_info.get('ip')
        self.user_agent = client_info.get('user_agent')
        self.browser = client_info.get('browser')
        self.os = client_info.get('os')
        self.device = client_info.get('device')
        self.referer = client_info.get('referer')
        self.language = client_info.get('language')
        self.screen_resolution = client_info.get('screen_resolution')
        self.timestamp = datetime.now().isoformat()
    
    def save(self):
        """Salva o acesso no banco de dados"""
        self.db.execute('''
            INSERT INTO accesses 
            (token_id, ip, user_agent, browser, os, device, referer, language, screen_resolution, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            self.token_id, self.ip, self.user_agent, self.browser,
            self.os, self.device, self.referer, self.language,
            self.screen_resolution, self.timestamp
        ))
        self.db.commit()
    
    @staticmethod
    def find_by_token(db, token_id, limit=100):
        """Busca acessos de um token específico"""
        accesses = db.execute(
            'SELECT * FROM accesses WHERE token_id = ? ORDER BY timestamp DESC LIMIT ?',
            (token_id, limit)
        ).fetchall()
        return [dict(a) for a in accesses]
    
    @staticmethod
    def find_all_with_token(db, limit=50):
        """Busca todos os acessos com informações do token"""
        accesses = db.execute('''
            SELECT a.*, t.name as token_name 
            FROM accesses a 
            JOIN tokens t ON a.token_id = t.id 
            ORDER BY a.timestamp DESC 
            LIMIT ?
        ''', (limit,)).fetchall()
        return accesses

class ClientInfo:
    """Classe para extrair informações do cliente"""
    
    @staticmethod
    def get_info(request):
        """Extrai informações do cliente a partir da requisição"""
        ua_string = request.headers.get('User-Agent', '')
        user_agent = parse(ua_string)
        
        return {
            'ip': request.headers.get('X-Forwarded-For', request.remote_addr),
            'user_agent': ua_string,
            'browser': f"{user_agent.browser.family} {user_agent.browser.version_string}",
            'os': f"{user_agent.os.family} {user_agent.os.version_string}",
            'device': 'Mobile' if user_agent.is_mobile else 'Tablet' if user_agent.is_tablet else 'Desktop',
            'referer': request.headers.get('Referer', 'Acesso direto'),
            'language': request.headers.get('Accept-Language', 'Desconhecido'),
            'screen_resolution': request.args.get('res', 'Desconhecida')
        }

class HoneyTokensApp:
    """Classe principal da aplicação Flask"""
    
    def __init__(self, database_path='honey_tokens.db'):
        self.app = Flask(__name__)
        self.database = Database(database_path)
        self.setup_routes()
        self.setup_app_context()
    
    def setup_app_context(self):
        """Configura o contexto da aplicação Flask"""
        
        @self.app.teardown_appcontext
        def close_connection(exception):
            self.database.close()
    
    def setup_routes(self):
        """Configura todas as rotas da aplicação"""
        
        @self.app.route('/')
        def index():
            db = self.database.get_db()
            tokens = Token.find_all(db)
            return render_template('index.html', tokens=tokens)
        
        @self.app.route('/create', methods=['POST'])
        def create_token():
            name = request.form.get('name', 'Token sem nome')
            description = request.form.get('description', '')
            
            db = self.database.get_db()
            token = Token(db, name=name, description=description)
            token.save()
            
            return redirect(url_for('index'))
        
        @self.app.route('/delete/<token_id>', methods=['POST'])
        def delete_token(token_id):
            db = self.database.get_db()
            token = Token.find_by_id(db, token_id)
            if token:
                token.delete()
            return redirect(url_for('index'))
        
        @self.app.route('/t/<token_id>')
        def trigger_token(token_id):
            db = self.database.get_db()
            token = Token.find_by_id(db, token_id)
            
            if token is None:
                return "Token não encontrado", 404
            
            client_info = ClientInfo.get_info(request)
            access = Access(db, token_id, client_info)
            access.save()
            
            return render_template('token.html', token=token)
        
        @self.app.route('/dashboard')
        def dashboard():
            db = self.database.get_db()
            tokens = Token.find_all(db)
            
            # Contagem de acessos por token
            token_stats = []
            for token in tokens:
                count = token.get_access_count()
                last_access = token.get_last_access()
                token_stats.append({
                    'token': token,
                    'count': count,
                    'last_access': last_access
                })
            
            # Todos os acessos para a tabela
            accesses = Access.find_all_with_token(db)
            
            return render_template('dashboard.html', token_stats=token_stats, accesses=accesses)
        
        @self.app.route('/api/accesses/<token_id>')
        def get_accesses(token_id):
            db = self.database.get_db()
            accesses = Access.find_by_token(db, token_id)
            return {'accesses': accesses}
    
    def run(self, debug=True, host='0.0.0.0', port=5000):
        """Inicia a aplicação Flask"""
        self.database.init_db()
        self.app.run(debug=debug, host=host, port=port)

# Ponto de entrada da aplicação
if __name__ == '__main__':
    app = HoneyTokensApp()
    app.run(debug=True, host='0.0.0.0', port=5000)