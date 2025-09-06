document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('loginForm');
  if (!form) {
    console.warn('[login] #loginForm não encontrado');
    return;
  }
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('email')?.value?.trim();
    const password = document.getElementById('password')?.value;
    const params = new URLSearchParams(window.location.search);
    const nextUrl = params.get('next') || '/';

    console.log('[login] enviando /auth/login…');
    try {
      const r = await fetch('/auth/login', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ email, password }),
        credentials: 'include'
      });
      console.log('[login] status', r.status);
      if (r.ok) {
        window.location.href = nextUrl;
      } else {
        const t = await r.text();
        alert('Falha no login: ' + t);
      }
    } catch (err) {
      console.error('[login] erro', err);
      alert('Erro de rede no login (veja o console).');
    }
  });
});
