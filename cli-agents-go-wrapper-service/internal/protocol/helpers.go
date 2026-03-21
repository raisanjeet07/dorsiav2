package protocol

import (
	"encoding/json"
	"time"

	"github.com/google/uuid"
)

// NewEnvelope creates an Envelope with a fresh ID and timestamp.
// Both sessionID and flow are required to match the routing contract.
func NewEnvelope(msgType MessageType, sessionID, flow string, payload any) (*Envelope, error) {
	raw, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	return &Envelope{
		ID:        uuid.New().String(),
		Type:      msgType,
		SessionID: sessionID,
		Flow:      flow,
		Timestamp: time.Now().UTC(),
		Payload:   raw,
	}, nil
}

// NewEnvelopeWithReplyTo is like NewEnvelope but sets ReplyTo (e.g. prompt.send message id).
func NewEnvelopeWithReplyTo(msgType MessageType, sessionID, flow, replyTo string, payload any) (*Envelope, error) {
	env, err := NewEnvelope(msgType, sessionID, flow, payload)
	if err != nil {
		return nil, err
	}
	env.ReplyTo = replyTo
	return env, nil
}

// NewReply creates a reply Envelope linked to the original message.
// Inherits sessionID and flow from the original.
func NewReply(original *Envelope, msgType MessageType, payload any) (*Envelope, error) {
	env, err := NewEnvelope(msgType, original.SessionID, original.Flow, payload)
	if err != nil {
		return nil, err
	}
	env.ReplyTo = original.ID
	return env, nil
}

// NewError creates an error Envelope.
func NewError(sessionID, flow, replyTo, code, message string) *Envelope {
	return &Envelope{
		ID:        uuid.New().String(),
		Type:      TypeErrorMsg,
		SessionID: sessionID,
		Flow:      flow,
		ReplyTo:   replyTo,
		Timestamp: time.Now().UTC(),
		Error: &ErrorPayload{
			Code:    code,
			Message: message,
		},
	}
}

// DecodePayload is a generic helper to unmarshal the Payload field.
func DecodePayload[T any](env *Envelope) (*T, error) {
	var v T
	if err := json.Unmarshal(env.Payload, &v); err != nil {
		return nil, err
	}
	return &v, nil
}
