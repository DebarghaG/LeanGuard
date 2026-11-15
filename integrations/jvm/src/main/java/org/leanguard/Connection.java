package org.leanguard;

import java.net.URI;
import java.util.Set;

final class Connection {
    private Connection() {}

    static URI validate(String url, String token) {
        URI uri = URI.create(url);
        boolean loopback = uri.getHost() != null &&
                Set.of("localhost", "127.0.0.1", "[::1]").contains(uri.getHost());
        if (uri.getHost() == null || uri.getUserInfo() != null || uri.getFragment() != null ||
                uri.getQuery() != null || !("https".equals(uri.getScheme()) ||
                ("http".equals(uri.getScheme()) && loopback))) {
            throw new IllegalArgumentException("Use HTTPS, or HTTP on loopback, without URL credentials or query parameters");
        }
        if (token == null || !token.matches("[A-Za-z0-9_-]{32,}")) {
            throw new IllegalArgumentException("Supply the deployment's URL-safe bearer credential");
        }
        return uri;
    }
}
