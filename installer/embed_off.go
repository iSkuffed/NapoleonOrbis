//go:build !embedpayload

package main

import "io/fs"

func embeddedPayload() fs.FS { return nil }
