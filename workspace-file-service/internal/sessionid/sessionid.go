// Package sessionid validates session identifiers for filesystem use.
package sessionid

import (
	"errors"
	"regexp"
	"strings"
)

const maxLen = 256

// Allowed: letters, digits, dot, underscore, hyphen (no slashes or "..").
var valid = regexp.MustCompile(`^[a-zA-Z0-9._-]+$`)

var (
	ErrEmpty   = errors.New("session id is empty")
	ErrTooLong = errors.New("session id too long")
	ErrInvalid = errors.New("session id contains invalid characters")
)

// Validate returns nil if id is safe to use as a single path segment.
func Validate(id string) error {
	id = strings.TrimSpace(id)
	if id == "" {
		return ErrEmpty
	}
	if len(id) > maxLen {
		return ErrTooLong
	}
	if id == "." || id == ".." {
		return ErrInvalid
	}
	if !valid.MatchString(id) {
		return ErrInvalid
	}
	return nil
}
