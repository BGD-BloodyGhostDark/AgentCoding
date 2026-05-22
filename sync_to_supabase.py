import os
import json
import ssl
import pg8000
from dotenv import load_dotenv

def main():
    # 載入 .env 檔案中的環境變數
    load_dotenv()
    
    project_ref = os.getenv("SUPABASE_PROJECT_REF")
    db_pass = os.getenv("SUPABASE_DB_PASS")
    
    if not project_ref or not db_pass:
        print("錯誤：.env 檔案中缺少 SUPABASE_PROJECT_REF 或 SUPABASE_DB_PASS 設定。")
        return

    # 建立 SSL context
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    # Supabase PostgreSQL 連線參數
    host = f"db.{project_ref}.supabase.co"
    port = 5432
    user = "postgres"
    database = "postgres"
    
    print(f"正在連接至 Supabase PostgreSQL 直連資料庫 ({host})...")
    
    # 建立資料庫連線
    try:
        conn = pg8000.connect(
            host=host,
            port=port,
            user=user,
            password=db_pass,
            database=database,
            ssl_context=ssl_context
        )
        cursor = conn.cursor()
        print("直連資料庫連線成功！")
    except Exception as e:
        print(f"直連資料庫連線失敗：{e}")
        print("嘗試使用 Transaction Pooler 連線...")
        try:
            # 備用方案：使用 Session Mode Pooler 連線 (port 5432)
            pooler_host = f"aws-0-ap-southeast-1.pooler.supabase.com"
            conn = pg8000.connect(
                host=pooler_host,
                port=5432,
                user=f"postgres.{project_ref}",
                password=db_pass,
                database=database,
                ssl_context=ssl_context
            )
            cursor = conn.cursor()
            print("資料庫連線成功 (Pooler)！")
        except Exception as ex:
            print(f"Pooler 資料庫連線也失敗：{ex}")
            return

    try:
        # 1. 建立 repositories 資料表
        print("正在建立 repositories 資料表...")
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS repositories (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            html_url TEXT NOT NULL,
            description TEXT,
            fork BOOLEAN DEFAULT false,
            language TEXT,
            stargazers_count INTEGER DEFAULT 0,
            forks_count INTEGER DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
        );
        """
        cursor.execute(create_table_sql)
        
        # 2. 開啟 Row Level Security (RLS) 並新增 SELECT policy
        print("正在設定資料表 RLS 安全性策略...")
        rls_sql = "ALTER TABLE repositories ENABLE ROW LEVEL SECURITY;"
        cursor.execute(rls_sql)
        
        # 建立唯讀 Policy，若已存在則先刪除
        policy_sql = """
        DROP POLICY IF EXISTS "Allow public read access" ON repositories;
        CREATE POLICY "Allow public read access" ON repositories FOR SELECT USING (true);
        """
        # pg8000 在執行多個 SQL 語句時，需要分開執行，以確保相容性
        try:
            cursor.execute('DROP POLICY IF EXISTS "Allow public read access" ON repositories;')
        except Exception:
            pass
        cursor.execute('CREATE POLICY "Allow public read access" ON repositories FOR SELECT USING (true);')
        
        conn.commit()
        print("資料表及安全性原則建立完成。")

        # 3. 讀取 repos.json 資料
        print("正在讀取 repos.json...")
        with open("repos.json", "r", encoding="utf-8") as f:
            repos = json.load(f)
            
        print(f"共讀取到 {len(repos)} 筆儲存庫資料，開始匯入...")
        
        # 4. UPSERT 資料至 repositories 表中
        upsert_sql = """
        INSERT INTO repositories (name, html_url, description, fork, language, stargazers_count, forks_count)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (name) DO UPDATE SET
            html_url = EXCLUDED.html_url,
            description = EXCLUDED.description,
            fork = EXCLUDED.fork,
            language = EXCLUDED.language,
            stargazers_count = EXCLUDED.stargazers_count,
            forks_count = EXCLUDED.forks_count;
        """
        
        success_count = 0
        for r in repos:
            # 處理欄位預設值或 None
            name = r.get("name")
            html_url = r.get("html_url")
            description = r.get("description")
            fork = r.get("fork", False)
            language = r.get("language")
            stargazers_count = r.get("stargazers_count", 0)
            forks_count = r.get("forks_count", 0)
            
            if not name or not html_url:
                continue
                
            cursor.execute(upsert_sql, (name, html_url, description, fork, language, stargazers_count, forks_count))
            success_count += 1
            
        conn.commit()
        print(f"同步完成！成功同步 {success_count} 筆資料至 Supabase 中。")
        
    except Exception as e:
        print(f"同步過程中發生錯誤：{e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()
