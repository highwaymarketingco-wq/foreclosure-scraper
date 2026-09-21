#!/usr/bin/perl
# run_timeout.pl SECONDS COMMAND [ARGS...]
#
# macOS ships neither timeout(1) nor gtimeout, so `timeout 900 git push` is a
# "command not found" here. Perl is always present. This runs COMMAND in its own
# process group, and when SECONDS elapse sends TERM to the whole group, then KILL
# after a 15 second grace. Exit status: the command's own, 124 on timeout (the
# same code GNU timeout uses), 127 if the command could not be started.
use strict;
use warnings;
no warnings "exec";
use POSIX qw(:sys_wait_h);

my $secs = shift @ARGV;
die "usage: run_timeout.pl SECONDS COMMAND [ARGS...]\n" unless defined $secs && $secs =~ /^\d+$/ && @ARGV;

my $pid = fork();
die "fork failed: $!\n" unless defined $pid;
if ($pid == 0) {
    setpgrp(0, 0);
    exec { $ARGV[0] } @ARGV or do { print STDERR "run_timeout: cannot exec $ARGV[0]: $!\n"; exit 127; };
}

my $timed_out = 0;
my $killed_at = 0;
$SIG{ALRM} = sub { $timed_out = 1; kill 'TERM', -$pid; $killed_at = time; };
for my $sig (qw(INT TERM HUP)) {
    $SIG{$sig} = sub { kill 'TERM', -$pid; };
}
alarm($secs) if $secs > 0;

my $status;
while (1) {
    my $r = waitpid($pid, WNOHANG);
    if ($r == $pid) { $status = $?; last; }
    if ($r == -1) { $status = 0; last; }
    if ($timed_out && time - $killed_at >= 15) { kill 'KILL', -$pid; $killed_at = time + 3600; }
    select(undef, undef, undef, 0.25);
}
exit 124 if $timed_out;
exit($status >> 8) if WIFEXITED($status);
exit(128 + ($status & 127));
