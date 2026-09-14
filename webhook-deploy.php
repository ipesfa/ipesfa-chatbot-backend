<?php
/**
 * Deploy automático del backend del chatbot (mismo patrón que el webhook
 * del tema): GitHub hace push -> pega acá -> git pull + reinstalar deps si
 * cambiaron + reiniciar Passenger.
 *
 * $secret y $venvActivate se leen del .env de esta misma carpeta (NO
 * versionado) en vez de estar hardcodeados acá — este archivo sí está en
 * git, así que cualquier valor puesto directo acá se pierde en el próximo
 * `git pull`. Agregar al .env del servidor:
 *   WEBHOOK_SECRET=<un secreto random>
 *   VENV_ACTIVATE=/home/USUARIO/virtualenv/RUTA_APP/3.x/bin/activate
 * (VENV_ACTIVATE es el "activate" del virtualenv que crea "Setup Python
 * App" de cPanel para esta aplicación).
 */

function ipesfa_read_env_var( string $name ): string {
	$path = __DIR__ . '/.env';
	if ( ! file_exists( $path ) ) {
		return '';
	}
	foreach ( file( $path ) as $line ) {
		$line = trim( $line );
		if ( $line === '' || $line[0] === '#' || strpos( $line, '=' ) === false ) {
			continue;
		}
		[ $key, $value ] = explode( '=', $line, 2 );
		if ( trim( $key ) === $name ) {
			return trim( $value );
		}
	}
	return '';
}

$secret = ipesfa_read_env_var( 'WEBHOOK_SECRET' );
$venvActivate = ipesfa_read_env_var( 'VENV_ACTIVATE' );

if ( ! $secret || ! $venvActivate ) {
	http_response_code( 500 );
	exit( 'Falta WEBHOOK_SECRET o VENV_ACTIVATE en el .env del servidor' );
}

$payload = file_get_contents( 'php://input' );
$signature = $_SERVER['HTTP_X_HUB_SIGNATURE_256'] ?? '';
$expected = 'sha256=' . hash_hmac( 'sha256', $payload, $secret );

if ( ! $signature || ! hash_equals( $expected, $signature ) ) {
	http_response_code( 403 );
	exit( 'Firma inválida' );
}

$repoDir = __DIR__;
$log = [];

$log[] = "== " . date( 'c' ) . " ==";
$before = trim( shell_exec( "cd " . escapeshellarg( $repoDir ) . " && git rev-parse HEAD" ) );
$log[] = shell_exec( "cd " . escapeshellarg( $repoDir ) . " && git pull origin main 2>&1" );
$after = trim( shell_exec( "cd " . escapeshellarg( $repoDir ) . " && git rev-parse HEAD" ) );

if ( $before !== $after ) {
	$changed = shell_exec(
		"cd " . escapeshellarg( $repoDir ) . " && git diff --name-only " . escapeshellarg( $before ) . ' ' . escapeshellarg( $after )
	);

	if ( strpos( (string) $changed, 'requirements.txt' ) !== false ) {
		$log[] = shell_exec(
			'source ' . escapeshellarg( $venvActivate ) . ' && pip install -r ' . escapeshellarg( $repoDir . '/requirements.txt' ) . ' 2>&1'
		);
	}

	// Passenger recarga la app cuando cambia el mtime de tmp/restart.txt.
	if ( ! is_dir( "$repoDir/tmp" ) ) {
		mkdir( "$repoDir/tmp" );
	}
	touch( "$repoDir/tmp/restart.txt" );
	$log[] = 'Restart solicitado.';
} else {
	$log[] = 'Sin cambios (ya estaba en el último commit).';
}

file_put_contents( __DIR__ . '/deploy.log', implode( "\n", $log ) . "\n\n", FILE_APPEND );

echo "OK\n";
