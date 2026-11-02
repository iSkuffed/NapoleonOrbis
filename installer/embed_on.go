//go:build embedpayload

package main

import (
	"embed"
	"io/fs"
)

//go:embed all:payload
var payloadFS embed.FS

// embeddedPayload returns the payload with payload/ as the root, so manifest.json is at the top.
func embeddedPayload() fs.FS {
	sub, err := fs.Sub(payloadFS, "payload")
	if err != nil {
		return nil
	}
	return sub
}
