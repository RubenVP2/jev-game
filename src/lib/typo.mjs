// Typographie française : espace fine insécable avant ? ! ; : et à l'intérieur des « ».
// Évite qu'un « ? » ou un « : » parte seul à la ligne.
const FINE = ' ';

export function fr(texte) {
  return texte
    .replace(/[  ]([?!;:»])/g, `${FINE}$1`)
    .replace(/«[  ]/g, `«${FINE}`);
}

/** Plugin rehype : applique fr() au texte des articles, sauf dans le code. */
export function rehypeFr() {
  const parcourir = (noeud) => {
    if (noeud.type === 'element' && (noeud.tagName === 'code' || noeud.tagName === 'pre')) return;
    if (noeud.type === 'text') noeud.value = fr(noeud.value);
    for (const enfant of noeud.children ?? []) parcourir(enfant);
  };
  return parcourir;
}
