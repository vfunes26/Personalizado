"""Parse a Telegram message into a validated profile (no network, no Qt).

The message is a plain ``CLAVE: valor`` block. Keys, codes, accents and case
are forgiving; values are normalised the way the official form expects them
(NIE and names in capitals without accents, e-mail in lowercase, phone digits).
The parser never stores anything: it only returns the fields that
``ProfileStore.save_profile`` accepts, plus a privacy-safe summary.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .config import REGRESO_PROCEDURE, TIE_PROCEDURE, _valid_nie

MAX_NAME = 50

# INE province codes for every label present in catalogs/snapshot-*.json.
PROVINCE_CODES = {
    '01': 'Araba', '02': 'Albacete', '03': 'Alicante', '04': 'Almería', '05': 'Ávila',
    '06': 'Badajoz', '07': 'Illes Balears', '08': 'Barcelona', '09': 'Burgos', '10': 'Cáceres',
    '11': 'Cádiz', '12': 'Castellón', '13': 'Ciudad Real', '14': 'Córdoba', '15': 'A Coruña',
    '16': 'Cuenca', '17': 'Girona', '18': 'Granada', '19': 'Guadalajara', '20': 'Gipuzkoa',
    '21': 'Huelva', '22': 'Huesca', '23': 'Jaén', '24': 'León', '25': 'Lleida',
    '26': 'La Rioja', '27': 'Lugo', '28': 'Madrid', '29': 'Málaga', '30': 'Murcia',
    '31': 'Navarra', '32': 'Ourense', '33': 'Asturias', '34': 'Palencia', '35': 'Las Palmas',
    '36': 'Pontevedra', '37': 'Salamanca', '38': 'S.Cruz Tenerife', '39': 'Cantabria',
    '40': 'Segovia', '41': 'Sevilla', '42': 'Soria', '43': 'Tarragona', '44': 'Teruel',
    '45': 'Toledo', '46': 'Valencia', '47': 'Valladolid', '48': 'Bizkaia', '49': 'Zamora',
    '50': 'Zaragoza', '51': 'Ceuta', '52': 'Melilla',
}
PROVINCE_ALIASES = {
    'BCN': 'Barcelona', 'MAD': 'Madrid', 'VLC': 'Valencia', 'SVQ': 'Sevilla', 'AGP': 'Málaga',
    'ALC': 'Alicante', 'BIO': 'Bizkaia', 'ZAZ': 'Zaragoza', 'PMI': 'Illes Balears',
    'BALEARES': 'Illes Balears', 'ISLAS BALEARES': 'Illes Balears', 'MALLORCA': 'Illes Balears',
    'TENERIFE': 'S.Cruz Tenerife', 'SANTA CRUZ DE TENERIFE': 'S.Cruz Tenerife',
    'LA CORUNA': 'A Coruña', 'CORUNA': 'A Coruña', 'ALAVA': 'Araba', 'VIZCAYA': 'Bizkaia',
    'GUIPUZCOA': 'Gipuzkoa', 'GERONA': 'Girona', 'LERIDA': 'Lleida', 'ORENSE': 'Ourense',
    'GRAN CANARIA': 'Las Palmas', 'ASTURIAS': 'Asturias', 'RIOJA': 'La Rioja',
}

PROCEDURE_CODES = {
    'TIE': TIE_PROCEDURE, 'HUELLAS': TIE_PROCEDURE, 'TOMA DE HUELLAS': TIE_PROCEDURE, '1': TIE_PROCEDURE,
    'REGRESO': REGRESO_PROCEDURE, 'AUTORIZACION DE REGRESO': REGRESO_PROCEDURE, '2': REGRESO_PROCEDURE,
}
ACCESS_CODES = {
    'CERTIFICADO': ('certificate', 'movil'), 'CERT': ('certificate', 'movil'),
    'CERTIFICADO ELECTRONICO': ('certificate', 'movil'), 'C': ('certificate', 'movil'),
    'CLAVE MOVIL': ('clave', 'movil'), 'MOVIL': ('clave', 'movil'), 'CM': ('clave', 'movil'),
    'CLAVE PERMANENTE': ('clave', 'permanente'), 'PERMANENTE': ('clave', 'permanente'),
    'CP': ('clave', 'permanente'),
    'SIN CLAVE': ('without_clave', 'movil'), 'SINCLAVE': ('without_clave', 'movil'),
    'SIN': ('without_clave', 'movil'), 'NO CLAVE': ('without_clave', 'movil'),
}
ANY_OFFICE = {'', 'CUALQUIERA', 'CUALQUIER', 'CUALQUIER OFICINA', 'ANY', 'TODAS', 'TODO', 'TODOS', '0'}
DOCUMENT_TYPES = {'NIE': 'NIE', 'DNI': 'DNI', 'PASAPORTE': 'PASSPORT', 'PASSPORT': 'PASSPORT'}
FILL_MODES = {'MANUAL': 'manual', 'MANO': 'manual', 'ACCESO': 'copy', 'DEL ACCESO': 'copy', 'COPIAR': 'copy'}

KEY_ALIASES = {
    'label': {'PERFIL', 'NOMBRE PERFIL', 'ETIQUETA', 'ALIAS'},
    'procedure': {'TRAMITE', 'SERVICIO', 'PROCEDIMIENTO'},
    'province': {'PROVINCIA', 'PROV'},
    'office': {'OFICINA', 'OF'},
    'access': {'ACCESO', 'AUTENTICACION', 'METODO', 'METODO ACCESO', 'LOGIN'},
    'document_type': {'DOCUMENTO', 'TIPO DOCUMENTO', 'TIPO DOC'},
    'document_number': {'NIE', 'NUMERO', 'NUMERO DOCUMENTO', 'NUM DOCUMENTO', 'DNI', 'PASAPORTE'},
    'full_name': {'NOMBRE', 'NOMBRE Y APELLIDOS', 'NOMBRE COMPLETO', 'APELLIDOS Y NOMBRE'},
    'nationality': {'NACIONALIDAD', 'PAIS', 'PAIS NACIONALIDAD'},
    'phone': {'TELEFONO', 'TEL', 'CELULAR', 'MOVIL CONTACTO'},
    'email': {'EMAIL', 'CORREO', 'E MAIL', 'CORREO ELECTRONICO'},
    'fill_mode': {'RELLENO', 'DATOS', 'MODO'},
}
_KEY_LOOKUP = {alias: key for key, aliases in KEY_ALIASES.items() for alias in aliases}
# Keys whose presence proves the message is a profile and not casual chat.
_STRONG_KEYS = {'procedure', 'province', 'access', 'document_number', 'nationality'}


def fold(text) -> str:
    """Uppercase, remove accents and collapse punctuation: ``S.Cruz`` -> ``S CRUZ``."""
    text = unicodedata.normalize('NFKD', str(text))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r'[^A-Z0-9]+', ' ', text.upper()).strip()


@dataclass(frozen=True)
class Catalog:
    provinces: tuple[str, ...]
    nationalities: tuple[str, ...]
    barcelona_offices: tuple[str, ...]

    @classmethod
    def load(cls, path: Path) -> 'Catalog':
        selectors = json.loads(Path(path).read_text(encoding='utf-8'))['selectors']
        def labels(name):
            return tuple(str(item['label']) for item in selectors[name]['options'])
        return cls(labels('provinces'), labels('nationalities'), labels('barcelona_offices'))

    @property
    def specific_offices(self) -> tuple[str, ...]:
        return tuple(o for o in self.barcelona_offices if fold(o) not in ANY_OFFICE and 'CUALQUIER' not in fold(o))


@dataclass
class IntakeResult:
    ok: bool
    fields: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    summary: str = ''
    full_summary: str = ''
    identity: tuple = ()


def looks_like_submission(text: str) -> bool:
    keys = {_KEY_LOOKUP.get(k) for k, _ in _split_lines(text)[0]}
    return len(keys & _STRONG_KEYS) >= 2


def _split_lines(text: str):
    pairs, rejected = [], []
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line or line.startswith('/') or line.startswith('#'):
            continue
        match = re.match(r'^([^:=]{1,40}?)\s*[:=]\s*(.*)$', line)
        if not match:
            rejected.append(line)
            continue
        pairs.append((fold(match.group(1)), match.group(2).strip()))
    return pairs, rejected


def _suggest(options, needle, limit=5):
    return [o for o in options if needle and needle in fold(o)][:limit]


def _resolve_choice(value, options, what, errors):
    """Exact fold match, else a unique prefix/substring match."""
    needle = fold(value)
    folded = {fold(o): o for o in options}
    if needle in folded:
        return folded[needle]
    candidates = [o for f, o in folded.items() if len(needle) >= 3 and f.startswith(needle)]
    if not candidates:
        candidates = [o for f, o in folded.items() if len(needle) >= 3 and needle in f]
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        errors.append(f'{what}: «{value}» es ambiguo. Opciones: ' + '; '.join(candidates[:5]))
    else:
        errors.append(f'{what}: «{value}» no está en el catálogo')
    return None


def resolve_province(value, catalog, errors):
    needle = fold(value)
    if re.fullmatch(r'\d{1,2}', needle) and needle.zfill(2) in PROVINCE_CODES:
        label = PROVINCE_CODES[needle.zfill(2)]
    elif needle in PROVINCE_ALIASES:
        label = PROVINCE_ALIASES[needle]
    else:
        return _resolve_choice(value, catalog.provinces, 'PROVINCIA', errors)
    if label not in catalog.provinces:
        errors.append(f'PROVINCIA: «{value}» no está en el catálogo')
        return None
    return label


def resolve_office(value, province, catalog, errors, warnings):
    needle = fold(value)
    if needle in ANY_OFFICE:
        return ''
    if province == 'Barcelona':
        offices = catalog.specific_offices
        if re.fullmatch(r'\d{1,2}', needle):
            index = int(needle)
            if 1 <= index <= len(offices):
                return offices[index - 1]
            errors.append(f'OFICINA: el número debe estar entre 1 y {len(offices)} (use /oficinas)')
            return None
        return _resolve_choice(value, offices, 'OFICINA', errors)
    warnings.append('OFICINA: solo se puede verificar contra el catálogo de Barcelona; '
                    'se guarda como preferencia y se marca con ⭐ si aparece en la lista.')
    return ' '.join(str(value).split())[:120].upper()


def normalize_name(value):
    text = unicodedata.normalize('NFKD', str(value))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch)).upper()
    return re.sub(r'\s+', ' ', text).strip()


def _mask(value, keep_start=1, keep_end=2):
    value = str(value)
    if len(value) <= keep_start + keep_end:
        return '*' * len(value)
    return value[:keep_start] + '*' * (len(value) - keep_start - keep_end) + value[-keep_end:]


def _mask_email(value):
    local, _, domain = value.partition('@')
    return (local[:1] + '***@' + domain) if domain else _mask(value)


def _initials(name):
    return ' '.join(part[0] + '.' for part in name.split())


def parse_submission(text: str, catalog: Catalog) -> IntakeResult:
    pairs, rejected = _split_lines(text)
    errors, warnings = [], []
    values = {}
    for raw_key, raw_value in pairs:
        key = _KEY_LOOKUP.get(raw_key)
        if key is None:
            errors.append(f'Campo desconocido: «{raw_key.title()}». Use /plantilla.')
            continue
        if key in values:
            errors.append(f'Campo repetido: «{raw_key.title()}»')
            continue
        values[key] = (raw_key, raw_value)
    for line in rejected:
        errors.append('Línea sin formato CLAVE: valor')
        break

    def get(key):
        item = values.get(key)
        return item[1].strip() if item and item[1].strip() else ''

    # --- tramite ---------------------------------------------------------------------------
    procedure = None
    if get('procedure'):
        needle = fold(get('procedure'))
        procedure = PROCEDURE_CODES.get(needle)
        if procedure is None and needle == fold(TIE_PROCEDURE):
            procedure = TIE_PROCEDURE
        if procedure is None and needle.startswith('POLICIA TOMA DE HUELLAS'):
            procedure = TIE_PROCEDURE
        if procedure is None:
            errors.append('TRAMITE: use TIE (toma de huellas) o REGRESO (autorización de regreso)')
    else:
        errors.append('TRAMITE: falta (TIE o REGRESO)')

    # --- provincia / oficina ------------------------------------------------------------
    province = None
    if get('province'):
        province = resolve_province(get('province'), catalog, errors)
    else:
        errors.append('PROVINCIA: falta (nombre o código de 2 dígitos, p. ej. 08)')
    office = resolve_office(get('office'), province, catalog, errors, warnings) if province else ''

    # --- acceso ------------------------------------------------------------------------
    access_mode = clave_method = None
    if get('access'):
        needle = fold(get('access'))
        if needle == 'CLAVE':
            errors.append('ACCESO: «CLAVE» es ambiguo; use CLAVE_MOVIL o CLAVE_PERMANENTE')
        elif needle in ACCESS_CODES:
            access_mode, clave_method = ACCESS_CODES[needle]
        else:
            errors.append('ACCESO: use CERTIFICADO, CLAVE_MOVIL, CLAVE_PERMANENTE o SIN_CLAVE')
    else:
        errors.append('ACCESO: falta (CERTIFICADO, CLAVE_MOVIL, CLAVE_PERMANENTE o SIN_CLAVE)')

    # --- relleno -----------------------------------------------------------------------
    fill_mode = 'manual'
    if get('fill_mode'):
        fill_mode = FILL_MODES.get(fold(get('fill_mode')))
        if fill_mode is None:
            errors.append('RELLENO: use MANUAL (datos del mensaje) o ACCESO (copiar tras entrar)')
            fill_mode = 'manual'
    if fill_mode == 'copy' and access_mode == 'without_clave':
        errors.append('RELLENO: ACCESO no se puede usar con SIN_CLAVE; use MANUAL')

    # --- documento ----------------------------------------------------------------------
    document_type = 'NIE'
    number_key = values.get('document_number', ('NIE', ''))[0]
    if number_key in DOCUMENT_TYPES:
        document_type = DOCUMENT_TYPES[number_key]
    if get('document_type'):
        document_type = DOCUMENT_TYPES.get(fold(get('document_type')), None)
        if document_type is None:
            errors.append('DOCUMENTO: use NIE, DNI o PASAPORTE')
            document_type = 'NIE'
    if procedure == TIE_PROCEDURE and document_type != 'NIE':
        errors.append('DOCUMENTO: la toma de huellas (TIE) solo admite NIE')
    number = re.sub(r'[\s\-.]', '', get('document_number')).upper()
    full_name = normalize_name(get('full_name'))
    if fill_mode != 'copy':
        if not number:
            errors.append('NIE: falta')
        elif document_type == 'NIE' and not _valid_nie(number):
            errors.append('NIE: formato o letra de control incorrectos (ej. X1234567L)')
        if not full_name:
            errors.append('NOMBRE: falta')
        elif len(full_name) > MAX_NAME or re.search(r'[^A-Z ]', full_name):
            errors.append(f'NOMBRE: solo letras y espacios, máximo {MAX_NAME} caracteres')

    # --- nacionalidad -------------------------------------------------------------------
    nationality = ''
    if procedure != REGRESO_PROCEDURE:
        if get('nationality'):
            nationality = _resolve_choice(get('nationality'), catalog.nationalities, 'NACIONALIDAD', errors) or ''
        else:
            errors.append('NACIONALIDAD: falta (p. ej. PERU)')
    elif get('nationality'):
        nationality = _resolve_choice(get('nationality'), catalog.nationalities, 'NACIONALIDAD', errors) or ''

    # --- contacto -----------------------------------------------------------------------
    phone = re.sub(r'[\s\-().]', '', get('phone')).lstrip('+')
    if not re.fullmatch(r'\d{6,15}', phone):
        errors.append('TELEFONO: de 6 a 15 dígitos, sin letras')
    email = get('email').strip().lower()
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        errors.append('EMAIL: dirección no válida')

    label = get('label') or ' · '.join(p for p in ('Telegram', province or '', 'TIE' if procedure == TIE_PROCEDURE else 'REGRESO' if procedure else '') if p)
    label = ' '.join(label.split())[:60]
    if errors:
        return IntakeResult(False, errors=errors, warnings=warnings)

    fields = dict(
        label=label,
        request=dict(access_mode=access_mode, clave_method=clave_method, no_slots_mode='salir',
                     applicant_no_slots_mode='wait', province=province, office=office,
                     procedure=procedure, subprocedure=None),
        applicant=dict(fill_mode=fill_mode, document_type=document_type, document_number=number,
                       full_name=full_name, nationality=nationality,
                       contact=dict(phone=phone, email=email)),
    )
    access_names = {'certificate': 'Certificado', 'clave': 'Cl@ve ' + str(clave_method).capitalize(),
                    'without_clave': 'Sin Cl@ve'}
    lines = [f'Perfil: {label}',
             f'Trámite: {"TIE · toma de huellas" if procedure == TIE_PROCEDURE else "Autorización de regreso"}',
             f'Provincia: {province}',
             f'Oficina: {office or "cualquiera (aviso con todas las oficinas disponibles)"}',
             f'Acceso: {access_names[access_mode]}']
    if fill_mode == 'copy':
        lines.append('Datos: se copian de la web tras entrar')
    else:
        lines += [f'{document_type}: {_mask(number)}', f'Nombre: {_initials(full_name)}']
    if nationality:
        lines.append(f'Nacionalidad: {nationality}')
    lines += [f'Teléfono: {_mask(phone, 0, 3)}', f'Correo: {_mask_email(email)}']
    full_lines = lines[:5]
    if fill_mode == 'copy':
        full_lines.append('Datos: se copian de la web tras entrar')
    else:
        full_lines += [f'{document_type}: {number}', f'Nombre: {full_name}']
    if nationality:
        full_lines.append(f'Nacionalidad: {nationality}')
    full_lines += [f'Teléfono: {phone}', f'Correo: {email}']
    return IntakeResult(True, fields=fields, warnings=warnings, summary='\n'.join(lines), full_summary='\n'.join(full_lines),
                        identity=(number, procedure, province, access_mode))


def template_text() -> str:
    return (
        '📋 Plantilla de perfil (copie, rellene y envíe tal cual)\n\n'
        'PERFIL: Mi perfil (opcional)\n'
        'TRAMITE: TIE\n'
        'PROVINCIA: 08\n'
        'OFICINA: CUALQUIERA\n'
        'ACCESO: CERTIFICADO\n'
        'NIE: X1234567L\n'
        'NOMBRE: MARIA LOPEZ GARCIA\n'
        'NACIONALIDAD: PERU\n'
        'TELEFONO: 600123456\n'
        'EMAIL: nombre@correo.com\n\n'
        '— Códigos —\n'
        'TRAMITE: TIE = toma de huellas (POLICÍA-TOMA DE HUELLAS… LEY 14/2013) · REGRESO = autorización de regreso\n'
        'PROVINCIA: nombre (Barcelona) o código INE de 2 dígitos (08). /provincias muestra la lista.\n'
        'OFICINA: CUALQUIERA (avisa con todas las oficinas que tengan cita), o parte del nombre '
        '(GRANOLLERS), o el número de /oficinas (solo Barcelona se verifica). '
        'La oficina elegida se marca con ⭐ en el aviso.\n'
        'ACCESO: CERTIFICADO · CLAVE_MOVIL · CLAVE_PERMANENTE · SIN_CLAVE\n'
        'Opcionales: RELLENO: MANUAL o ACCESO (copiar de la web; no con SIN_CLAVE) · '
        'DOCUMENTO: NIE/DNI/PASAPORTE (solo REGRESO; también puede usar DNI: o PASAPORTE: en lugar de NIE:)\n\n'
        '— Formato —\n'
        'Mayúsculas o minúsculas da igual: el bot pone NIE y nombre en MAYÚSCULAS sin tildes ni Ñ, '
        'y el correo en minúsculas. Teléfono solo dígitos (se ignoran espacios, guiones y +).\n'
        'Una línea por campo, con «CLAVE: valor».\n\n'
        '🔒 El bot borra su mensaje tras leerlo (si Telegram lo permite) y responde con los datos guardados para que confirmes que son correctos.'
    )


def provinces_text(catalog: Catalog) -> str:
    by_label = {label: code for code, label in PROVINCE_CODES.items()}
    rows = [f'{by_label.get(label, "--")} {label}' for label in catalog.provinces]
    rows.sort()
    return '🗺 Provincias (código INE y nombre)\n\n' + '\n'.join(rows)


def offices_text(catalog: Catalog) -> str:
    rows = [f'{i}. {office}' for i, office in enumerate(catalog.specific_offices, 1)]
    return ('🏢 Oficinas de Barcelona (use el número o parte del nombre en OFICINA)\n'
            'CUALQUIERA = cualquier oficina\n\n' + '\n'.join(rows))
