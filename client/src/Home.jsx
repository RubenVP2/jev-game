import { useState } from 'react';

export default function Home({ onJoin, error }) {
  const params = new URLSearchParams(location.search);
  const [name, setName] = useState(localStorage.getItem('sp-name') || '');
  const [code, setCode] = useState((params.get('room') || '').toUpperCase());
  const ok = name.trim().length > 0;

  return (
    <div className="home">
      <div className="panel home-card">
        <h1 className="logo">SUBTERFUGE<span>PROTOCOL</span></h1>
        <p className="tagline">Déduction sociale · Extraction sous contrainte audio · Arbitrage Kev</p>
        <label>Nom de code
          <input value={name} maxLength={16} onChange={(e) => setName(e.target.value)} placeholder="ex. Nyx" autoFocus />
        </label>
        <button className="primary" disabled={!ok} onClick={() => onJoin('', name.trim())}>Créer un salon</button>
        <div className="or">ou</div>
        <div className="row">
          <input value={code} maxLength={4} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="CODE" className="code-input" />
          <button disabled={!ok || code.length !== 4} onClick={() => onJoin(code, name.trim())}>Rejoindre</button>
        </div>
        {error && <p className="error">{error}</p>}
        <details className="rules">
          <summary>Règles en 30 secondes</summary>
          <ul>
            <li><b>Opérateur</b> : voit l'alignement des 16 terminaux, transmet un indice (1 mot + 1 chiffre) validé par Kev.</li>
            <li><b>Infiltrés</b> : explorent le complexe à la lampe torche, débattent à la voix (audio spatialisé) et valident les terminaux par contact.</li>
            <li><b>La Taupe</b> : infiltré secret qui voit le Patrouilleur et pousse l'équipe vers les pièges.</li>
            <li>Pièges → alarme, banque corrompue, le Patrouilleur traque le plus bruyant. Protocole Fatal → victoire de la Taupe.</li>
            <li>Toutes les cibles trouvées → ascenseur ouvert 30 s : rejoignez-le et votez pour éjecter la Taupe.</li>
            <li>3 manches, 75 % des banques (9/12) requises pour gagner.</li>
          </ul>
        </details>
      </div>
    </div>
  );
}
