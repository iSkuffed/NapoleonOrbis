//go:build embedpayload

package main

import "testing"

// Run with a payload in ./payload (GN_WRITE_FIXTURE=payload go test -run WriteFixture first).
func TestEmbeddedPayloadLoads(t *testing.T) {
	fsys := embeddedPayload()
	if fsys == nil {
		t.Fatal("no embedded payload")
	}
	p, err := loadPayload(fsys)
	if err != nil {
		t.Fatal(err)
	}
	if p.M.Version != "synth" || len(p.M.ModPacks) != 1 {
		t.Fatalf("manifest: %+v", p.M)
	}
	if q, err := openPayload(""); err != nil || q.M.Version != "synth" {
		t.Fatalf("openPayload default: %v", err)
	}
}
