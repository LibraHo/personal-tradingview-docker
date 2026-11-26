import {createContext, useContext, useEffect, useRef, useState, type ReactNode} from 'react';
import {Moon, Sun} from 'lucide-react';
import './theme.css';

type Theme = 'dark' | 'light';
const storageKey = 'nas-market-theme';
const endpoint = location.pathname.startsWith('/trade') ? '/api/market/settings/theme' : '/api/settings/theme';
const ThemeContext = createContext<{
  theme: Theme;
  toggleTheme: () => void;
  ready: boolean;
  saving: boolean;
  error: string;
}>({
  theme: 'dark', toggleTheme: () => {}, ready: false, saving: false, error: '',
});

function readTheme(): Theme {
  try {
    return localStorage.getItem(storageKey) === 'light' ? 'light' : 'dark';
  } catch {
    return 'dark';
  }
}

async function sharedTheme(body?: {value: Theme; initialize?: boolean}): Promise<{value: Theme | null}> {
  const response = await fetch(endpoint, {
    method: body ? 'PUT' : 'GET',
    cache: 'no-store',
    signal: AbortSignal.timeout(10000),
    headers: body ? {'Content-Type': 'application/json'} : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok || !['dark', 'light', null].includes(data.value)) {
    throw new Error('主题设置暂不可用');
  }
  return data;
}

const initialTheme = readTheme();
document.documentElement.dataset.theme = initialTheme;

export function ThemeProvider({children}: {children: ReactNode}) {
  const [theme, setTheme] = useState(initialTheme);
  const [ready, setReady] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const savedTheme = useRef(initialTheme);
  const writing = useRef(false);
  const generation = useRef(0);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(storageKey, theme);
    } catch {
      // The shared setting still works when the browser cache is unavailable.
    }
  }, [theme]);

  useEffect(() => {
    let active = true;
    let reading = false;
    async function refresh() {
      if (reading || writing.current || document.hidden) return;
      reading = true;
      const expectedGeneration = generation.current;
      try {
        let shared = await sharedTheme();
        if (shared.value === null) {
          shared = await sharedTheme({value: initialTheme, initialize: true});
        }
        if (active && !writing.current && expectedGeneration === generation.current && shared.value) {
          savedTheme.current = shared.value;
          setTheme(shared.value);
          setReady(true);
          setError('');
        }
      } catch {
        if (active && !writing.current && expectedGeneration === generation.current) {
          setReady(true);
          setError('读取共享主题失败，请稍后重试');
        }
      } finally {
        reading = false;
      }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    const onFocus = () => void refresh();
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
    };
  }, []);

  async function toggleTheme() {
    if (!ready || writing.current) return;
    const next = theme === 'light' ? 'dark' : 'light';
    const previous = savedTheme.current;
    writing.current = true;
    generation.current++;
    setSaving(true);
    setError('');
    setTheme(next);
    try {
      const shared = await sharedTheme({value: next});
      if (!shared.value) throw new Error('主题未保存');
      savedTheme.current = shared.value;
      setTheme(shared.value);
    } catch {
      setTheme(previous);
      setError('主题保存失败，请重试');
    } finally {
      writing.current = false;
      setSaving(false);
    }
  }

  return <ThemeContext.Provider value={{theme, toggleTheme, ready, saving, error}}>
    {children}
  </ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext).theme;
}

export function ThemeToggle() {
  const {theme, toggleTheme, ready, saving, error} = useContext(ThemeContext);
  const light = theme === 'light';
  const label = light ? '切换到夜间主题' : '切换到白天主题';
  return <>
    <button type="button" className="theme-toggle" aria-label={label}
      title={saving ? '正在保存主题' : label} disabled={!ready || saving}
      aria-busy={saving} onClick={() => void toggleTheme()}>
      {light ? <Moon size={16} aria-hidden="true"/> : <Sun size={16} aria-hidden="true"/>}
    </button>
    {error && <span className="theme-sync-error" role="alert">{error}</span>}
  </>;
}
