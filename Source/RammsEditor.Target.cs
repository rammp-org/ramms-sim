// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;
using System.Collections.Generic;

public class RammsEditorTarget : TargetRules
{
	public RammsEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.V7;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_8;
		ExtraModuleNames.Add("Ramms");

		// URLab v0.6.0-beta's generated MuJoCo component model (hundreds of
		// reflected classes over template-heavy ProtoSpec headers) makes the
		// default jumbo Module.URLab.gen.N.cpp unity TUs explode clang to
		// ~25 GB each. Compile generated files individually on Mac and Linux;
		// MSVC handles the batched TUs fine, so keep them fast. Linux clang 20
		// peaks at 11+ GB per URLab TU at -O3, which runs a 32 GB machine out
		// of memory, so it takes the same settings as Mac.
		if (Target.Platform == UnrealTargetPlatform.Mac || Target.Platform == UnrealTargetPlatform.Linux)
		{
			bAlwaysUseUnityForGeneratedFiles = false;

			// Even single hand-written URLab TUs (MjFromtoFold.cpp,
			// MjSpecWriteHooks.cpp, URLabEditor unity blobs) peak 14-17 GB
			// under clang's -O3 backend, which starves a 32 GB machine.
			// Compile the URLab modules unoptimized and un-batched on Mac and
			// Linux: the MuJoCo core is a prebuilt optimized shared library
			// (.dylib on Mac, .so on Linux), so physics stepping keeps its
			// speed — only URLab's glue slows, which dev builds tolerate.
			DisableOptimizeCodeForModules = new string[] { "URLab", "URLabEditor", "URLabRos" };
			DisableUnityBuildForModules = new string[] { "URLab", "URLabEditor", "URLabRos" };
		}
	}
}
