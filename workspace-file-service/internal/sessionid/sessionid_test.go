package sessionid

import "testing"

func TestValidate(t *testing.T) {
	tests := []struct {
		id    string
		valid bool
	}{
		{"", false},
		{"..", false},
		{"../x", false},
		{"a/b", false},
		{"wf-123", true},
		{"research-my-session-3", true},
		{string(make([]byte, maxLen+1)), false},
	}
	for _, tc := range tests {
		err := Validate(tc.id)
		if tc.valid && err != nil {
			t.Errorf("%q: want nil, got %v", tc.id, err)
		}
		if !tc.valid && err == nil {
			t.Errorf("%q: want error, got nil", tc.id)
		}
	}
}
